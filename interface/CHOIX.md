# OR'CHESTRE — choix de conception de l'interface

Ce document explique les décisions prises pour construire l'interface d'aide à la décision à partir
du dépôt `ias-orchestre`. Les points qui demandent un arbitrage de l'équipe sont regroupés à la fin
(§ 10, « Questions ouvertes »).

---

## 1. Technologie : Streamlit, 100 % Python

* Le dépôt contenait deux maquettes Streamlit (`app.py`, `app_chirurgien.py`), reprises comme point de départ
  (parcours « ajouter un patient → propositions → choix », grille des vacations, validation des codes CIM-10 /
  CCAM par expressions régulières) au lieu d'introduire un autre framework ; elles ne sont plus dans le dépôt.
* Navigation multipage native (`st.navigation`), graphiques Plotly (Gantt interactif au survol),
  base SQLite locale (aucun serveur à installer).

```
interface/
├── app.py                 point d'entrée : connexion, rôles, navigation
├── orchestre/             NOYAU sans interface graphique (testable)
│   ├── chemins.py         accès aux dossiers du dépôt (sys.path), commun/ en premier
│   ├── ml.py              modèles .joblib, vocabulaires, prédiction, métriques sur le jeu de test
│   ├── programme.py       planning v28, niveau 1 (instance d'étude), programme niveau 2 (hybridation)
│   ├── sma_service.py     rejeu des événements dans le SMA, inscription, annulation
│   └── stockage.py        SQLite, chiffrement, comptes, traces, purge RGPD
├── vues/                  une page par onglet + graphiques
├── tests/                 tests du noyau (pytest)
└── donnees/               base locale, clé, caches — créé au lancement, ignoré par git
commun/
├── parametres.py          capacités, budget, graines, horizons : définis UNE seule fois
├── structures_communes.py version FUSIONNÉE des classes communes (voir § 2), occupation des lits
└── validation.py          validateur de faisabilité indépendant (niveaux 1 et 2)
```

## 2. Une seule version des classes communes

Le dépôt contenait **deux copies divergentes** de `structures_communes.py` :

| Copie | Contient en plus |
|---|---|
| `planning_vacations/` (utilisée par le SMA et le planning v28) | parité des semaines : `type_semaine`, `planning_pour_semaine`, `Vacation.semaines` |
| `metaheuristiques/` (utilisée par l'hybridation) | priorité : `penalite_priorite_patient` |

Comme tout le système doit partager les mêmes classes (`Patient`, `Vacation`, `InstanceNiveau2`…),
j'ai créé `commun/structures_communes.py`, **union exacte des deux** (aucune fonction modifiée), et
l'interface le charge **avant** les autres. Ainsi un `Patient` créé en consultation est exactement
celui qu'attendent les métaheuristiques et les agents. Les deux copies ont ensuite été supprimées :
`hybridation.py`, `sorties.py`, `planning_vacations_v28.py` et `sma_urgences.py` ajoutent
`commun/` à leur `sys.path` et fonctionnent aussi lancés seuls (sorties identiques avant / après).

## 3. Chaîne de décision

```
 Consultation ──► ML (4 modèles) + règle d'urgence ──► validation par le chirurgien ──┐
                                                                    ▼
 Planning v28 (vacations fixes) ──► Métaheuristiques / hybridation ──► Programme initial
                                    (patients → vacations, niveau 2)        │ validateur de faisabilité
                                                                            ▼
 Urgences, pannes, absences, prolongations, lits fermés,
 annulations, nouvelles inscriptions ──► SMA (Mesa) ──► Programme courant
```

**Séparation des niveaux (D6).** Le niveau 1 (chirurgiens → plages horaires) est étudié sur l'**instance d'étude
fictive** (8 chirurgiens, 3 salles, blocs de 2 h). Le niveau 2 (patients → vacations) et le SMA travaillent sur le
**planning réel v28** (vacations fixes). Les deux ne sont chaînés que sur l'instance d'étude
(`hybridation.py --instance etude`).

**Paramètres (`commun/parametres.py`).** Capacités, budget de calcul, graines et horizons y sont définis une seule
fois ; aucun autre fichier ne les écrit en dur.

| Paramètre | Valeur | Utilisé par |
|---|---|---|
| Lits / dont réserve des urgences / places ambulatoires du site | 30 / 3 / 20 | application, N2 et SMA sur v28 (D4) |
| Lits / réserve / places de l'instance d'étude N1 | 14 / 2 / 10 | instance d'étude fictive uniquement |
| Budget de calcul d'une métaheuristique | 10 s | interface, `hybridation.py --temps` |
| Graines | 42 (étude, Mesa, ML, saturation), 43 (patients), 1 (scénarios SMA) | option `--graine` de chaque script |
| Horizon du programme / du SMA / des reports | 4 semaines / 52 semaines / 3 semaines | programme, SMA, hybridation |

Les capacités du site restent à remplacer par les capacités réelles (§ 10).

**Validateur de faisabilité (D9, `commun/validation.py`).** Indépendant des fonctions objectif et des algorithmes,
il contrôle au niveau 1 l'affectation, les plages, les salles autorisées, les disponibilités, les conflits de salle
et de chirurgien, et au niveau 2 l'affectation, la vacation, le chirurgien, la date au plus tôt, la capacité utile
des vacations, les lits et les places. Chaque résultat de métaheuristique et le programme de l'interface portent
leur validation ; la meilleure solution retenue est une solution faisable, et une solution non faisable est
signalée « NON VALIDE ». Dans l'onglet Planning, la régulation et l'administrateur voient un bandeau rouge et la
liste des contraintes violées.

**Occupation des lits et des places (Q13).** Une seule fonction de décompte (`periodes_occupation`) sert au niveau 2,
au SMA, aux indicateurs, à l'étude de saturation et au validateur :

* un patient hospitalisé occupe un lit par **nuitée**, de son admission (jour de l'intervention moins les nuits
  avant) à la veille de sa sortie ; il sort à **midi** (`HEURE_SORTIE_HOSPITALISATION`) et son lit est réutilisable
  le même jour après **remise en état** par le service de nettoyage (`DUREE_REMISE_EN_ETAT_LIT_MIN` = 60 min) ;
  jamais deux patients à la fois dans un lit ; un hospitalisé sans nuitée occupe un lit le jour de son intervention ;
* un patient ambulatoire occupe une place une **demi-journée** : le matin si son intervention commence avant 13 h
  (`HEURE_DEBUT_APRES_MIDI_AMBULATOIRE` ; au niveau 2, début de la vacation), l'après-midi sinon. Le patient du matin
  libère sa place à 13 h ; après 1 h de remise en état (`DUREE_REMISE_EN_ETAT_PLACE_MIN`), elle accueille un patient
  de l'après-midi. La capacité se vérifie par demi-journée ; l'affichage par jour montre le pic de la journée.

## 4. Onglet Consultation (machine learning)

* **Entrées demandées = exactement les 11 variables des modèles** (`CAT_COLS + NUM_COLS` de
  `modele_prediction_rapide.py`) : type d'intervention, CIM-10 principal, CCAM 1, sexe, praticien,
  type d'anesthésie, anesthésie loco-régionale, âge, année, mois, jour de la semaine.
  * année / mois / jour de semaine sont **déduits de la date « opérable au plus tôt »** (les modèles ont
    appris sur la date d'intervention ; prendre la date du jour biaiserait ces trois variables).
  * listes déroulantes = **modalités vues à l'entraînement**, lues dans l'encodeur interne du modèle,
    avec saisie libre possible (une valeur inconnue du modèle est traitée comme manquante, sans avertissement).
* **Non collectés** (minimisation) : nom, prénom, date de naissance (l'âge suffit), CIM associés 1-5 et
  CCAM 2-4 (présents dans les données mais **inutilisés** par les modèles).
* **Modèles utilisés** : les 4 modèles du dépôt (`machine_learning/outputs/models_rapide/*.joblib` : type de prise
  en charge, durée au bloc, nuits avant, nuits après), appelés via `predire_patient()` de `utilisation_modele.py`.
  Préparation des données, découpage et évaluation sont communs (`machine_learning/preparation.py`) : un seul
  découpage **80 % entraînement / 20 % test** stratifié (graine `GRAINE_ML`), nuits avant / après apprises et
  évaluées sur les seuls hospitalisés. La qualité affichée est recalculée par l'interface
  (`valider_sur_jeu_de_test`) ; seules des métriques agrégées sont conservées (`donnees/metriques_ml.json`).
* **Score d'urgence (D8)** : il n'est pas prédit par un modèle. C'est une **règle du projet** (`regle_urgence`,
  d'après le code CIM-10 principal et le premier acte CCAM), **non validée cliniquement**. Le score 1-10 donne une
  **priorité proposée** 1-4 (1-2 → 1, 3-4 → 2, 5-7 → 3, 8-10 → 4) que le médecin valide ou corrige.
  Au-delà de 8, l'interface conseille de passer par l'onglet Urgences.
* **Le chirurgien valide ou corrige** chaque valeur (prise en charge, durée, nuits, priorité). La
  prédiction ET la valeur retenue sont conservées (on peut mesurer l'écart a posteriori).
* Durée arrondie à 5 min (15 min minimum) ; un patient hospitalisé a au moins 1 nuit post-opératoire.
* Date au plus tôt ≥ lendemain (une consultation ne programme pas une chirurgie réglée le jour même ;
  le jour même relève de l'onglet Urgences).

## 5. Onglet Planning (métaheuristiques)

* **Vacations des chirurgiens** : planning fixe `planning_vacations_v28.py` (comme demandé pour la
  première version), avec la parité automatique (cycle impaire A / paire / impaire B / paire) et les
  plages URGENCES / LIBRE.
* **Programme opératoire** (niveau 2 : patients → vacations) calculé par **`hybridation.py`**
  (AGS + RS + Tabou), mode « mémétique » par défaut. Tous les modes de l'hybridation (mémétique,
  AGS>RS>TABOU, RS>AGS>TABOU, et les références RS / Tabou / AGS seuls) et le glouton commun sont
  proposés, avec le même départ et le même budget.
* **Une seule implémentation par algorithme** : celle de `hybridation.py`, qui s'appuie uniquement sur
  `structures_communes.py` et `sorties.py`. Les anciennes versions autonomes (recherche taboue avec ses
  propres classes, recuit simulé et AGS seuls) ont été retirées du dépôt (voir NETTOYAGE.md).
* **Niveau 1 (chirurgiens → plages)** : l'hybridation N1 travaille sur des blocs de 2 h. Le planning v28
  a des horaires irréguliers (7 h 45, 15 h 30…) et n'est donc pas ré-optimisable tel quel. L'onglet lance
  le niveau 1 sur l'**instance d'étude fictive** (8 chirurgiens, 3 salles) et affiche le planning obtenu (D6).
  Brancher le N1 sur v28 demande de définir une grille de créneaux (question ouverte § 10).
* **Programme initial fictif** : le dépôt ne contient pas de liste de patients à programmer. J'utilise le
  générateur commun `generer_patients_etude` (patients `DEMO-xxxx`) sur un **horizon de 4 semaines**, avec
  une charge décroissante (85-100 %, 60-75 %, 35-50 %, 10-25 % des heures de vacation) : un programme se
  remplit à l'approche de la date, et il reste de la place pour les nouvelles consultations.
* **Hébergement (D4)** : 30 lits dont 3 de réserve pour les urgences, 20 places ambulatoires, pour l'application,
  le niveau 2 et le SMA sur v28 ; l'instance d'étude du niveau 1 garde ses propres capacités (14 lits dont 2 de
  réserve, 10 places), calibrées pour 8 chirurgiens. L'administrateur peut modifier les capacités du site
  (Administration → Lits et places). À remplacer par les capacités réelles (question ouverte).

### Générateurs de patients (D7)

Trois générateurs, aux objectifs différents, volontairement séparés :

| Générateur | Objectif | Distributions | Graine |
|---|---|---|---|
| `generer_patients_etude` (`commun/structures_communes.py`) | instances d'optimisation : instance d'étude, programme de démonstration, scénarios du SMA | **hypothèses** : durée uniforme dans {30…150} min, 40 % d'ambulatoires, nuits avant / après fixées, priorités 15 / 50 / 25 / 10 %, 5 % d'urgences, charge 90-110 % des vacations | `GRAINE_PATIENTS` (+ 97 par semaine) |
| `tirer_patients_profils_reels` (`interface/tests/saturation.py`) | étude de saturation | durée, mode et nuits **observés** (séjour tiré au hasard dans les données hospitalières, lues en mémoire, rien n'est écrit) ; chirurgien au prorata du temps de vacation, priorité 2 (hypothèses) | `GRAINE_SATURATION` |
| `urgences_semaine_aleatoire` (`sma/scenarios_sma.py`) | arrivées d'urgences des scénarios du SMA | jour, heure, durée, ambulatoire, nuits calibrés sur l'historique 2019-2022 ; gravités et praticiens : hypothèses | `GRAINE_SCENARIOS_SMA` |

## 6. Onglet Urgences (système multi-agent)

* **Le SMA du dépôt est utilisé tel quel** (`sma/sma_urgences.py`, Mesa, agents Triage, Régulation, Salle,
  Chirurgien, Hébergement, Logistique, protocole Contract Net). L'interface permet de déclarer une
  urgence (gravité vitale / urgente / différable), une panne, une prolongation ou une fin de panne du
  monte-lit, une absence, la prolongation d'une intervention, des lits indisponibles, et affiche décisions,
  alertes, Gantt de la journée et messages FIPA-ACL.
* **Approche événementielle (« event sourcing »)** : la base ne stocke que le programme initial et la liste
  des événements ; l'état du bloc est obtenu en **rejouant** les événements dans un modèle Mesa neuf
  jusqu'à l'heure courante (≈ 0,5 s). Avantages : état reproductible et vérifiable
  (`verifier_coherence()`), historique complet pour la traçabilité, et l'effacement d'un patient (RGPD) se
  propage naturellement (on retire ses événements et on rejoue).
* **Insertion des patients de consultation** (le SMA d'origine ne gérait que les urgences et les pannes) :
  j'ai ajouté, **sans modifier les agents**, un événement « inscription » qui réutilise l'appel d'offres
  `cfp_replacement` de l'agent de Régulation ; les agents Chirurgien et Hébergement valident chaque
  proposition. Les 4 meilleures (une par créneau) sont **présentées au chirurgien, qui choisit**. Au
  rejeu, le créneau choisi est réappliqué ; s'il n'est plus possible, la meilleure alternative est prise.
  Le planning des vacations étant connu sur 52 semaines, un créneau plus tardif existe presque toujours ; la
  liste d'attente (relancée chaque matin à 7 h par la Régulation) ne sert qu'en dernier recours.
* **Annulation** : un événement libère le créneau et la Régulation relance la liste d'attente.
* Correctif côté interface : pour un patient de consultation, l'heure « initiale » de référence est celle
  de son **premier placement** (sinon le bilan du SMA le comptait comme « décalé » depuis minuit).
* Une urgence est enregistrée **à l'heure courante** (pas de saisie rétroactive, qui réécrirait l'histoire).
* **Horloge** : temps réel (Europe/Paris) par défaut ; l'administrateur peut figer une **heure de
  démonstration** et l'avancer (+30 min, +2 h, lendemain 7 h 30) pour montrer le SMA en action.
* Spécialités : tous les praticiens du planning sont dans le même service (`SPECIALITE_SERVICE`,
  orthopédie-traumatologie) ; un confrère du service peut reprendre un patient qui l'a accepté.

### Aléas gérés par le SMA

| Aléa | Événement | Traitement |
|---|---|---|
| Urgence | `ArriveeUrgence` | appel d'offres aux salles, délai selon la gravité ; escalade jusqu'au planning de garde (niveau 4) ; **transfert proposé** (niveau 5, D12) si aucun chirurgien compétent pour la spécialité de l'urgence, garde comprise, ne peut opérer avant la limite acceptable : décision `urgence_transferee` et alerte « décision humaine requise : transfert proposé » ; le meilleur plan interne éventuel est gardé ; le SMA ne transfère jamais de lui-même. Spécialités couvertes par la garde : `ParametresSMA.specialites_garde` (spécialité du service) |
| Panne du monte-lit | `PanneAscenseur`, `ProlongationPanne`, `FinPanne` | aucun patient hospitalisé brancardé pendant la panne ; suite du programme décalée |
| Absence d'un chirurgien | `AbsenceChirurgien` | vacations fermées ; patients replacés au plus tôt 2 jours après la déclaration ; confrère seulement si accepté ; urgences dans leur délai ; alerte pour un patient prioritaire repoussé de plus de 3 jours ou qui commence dans l'heure |
| Prolongation d'une intervention | `ProlongationIntervention` | la salle réordonne la suite du créneau ; les patients qui ne tiennent plus dans les heures du créneau sont replacés (pas d'heures supplémentaires) ; salle de réveil et brancardage pris en compte |
| Lits indisponibles | `IndisponibiliteLits` | capacité réduite sur la période, **d'abord sur les lits programmables** (la réserve des urgences reste entière tant qu'il reste assez de lits) ; patients hospitalisés non commencés déplacés, priorité la plus faible puis intervention la plus tardive d'abord ; liste d'attente relancée à la fin de la période |
| Annulation, nouvelle inscription | événements du site « annulation », « inscription » | créneau libéré et liste d'attente relancée / appel d'offres de replacement |

## 7. Protection des données (RGPD / recommandations CNIL)

| Principe | Mise en œuvre |
|---|---|
| Minimisation | âge au lieu de la date de naissance, ni nom ni prénom, pas de variables inutilisées |
| Pseudonymisation | pseudonyme `PAT-AA-NNNN` partout ; référence de dossier (IPP) facultative **chiffrée** (Fernet, clé hors base, ou variable d'environnement `ORCHESTRE_CLE`) |
| Authentification | comptes nominatifs, 3 rôles, mots de passe PBKDF2-SHA256 (310 000 itérations), politique CNIL (12 caractères, 4 types), changement obligatoire à la 1re connexion, blocage 15 min après 5 échecs, déconnexion après 15 min d'inactivité |
| Habilitations | chirurgien : ses patients, son code praticien imposé ; régulation : tous les patients, recalcul du programme ; administrateur : comptes, horloge, conservation, traces |
| Traçabilité | journal des connexions, prédictions, créations, déchiffrements, exports, suppressions (6 mois) |
| Conservation | purge automatique N jours après l'intervention (30 j par défaut, paramétrable) |
| Droits | export JSON (accès / portabilité), effacement propagé au programme |
| Transparence / art. 22 | prédictions et créneaux = propositions ; décision humaine ; qualité du modèle affichée ; notice d'information patient téléchargeable (onglet Confidentialité) ; case « patient informé » obligatoire |
| Données d'entraînement | aucune ligne de l'historique n'est affichée ni copiée ; seules des métriques agrégées |
| Fichiers sensibles | `interface/donnees/` (base, clé, comptes de démo) ignoré par git, droits 600 |

**Hors de portée d'une application seule** (rappelé dans l'onglet Confidentialité) : hébergement certifié
**HDS**, **AIPD**, inscription au registre et avis du DPO, authentification forte (CPS / Pro Santé Connect),
HTTPS.

**Alerte** : le dépôt GitHub est **public** et contient `machine_learning/donnees_hospitalieres.csv`
(dates de naissance, dates de séjour, identifiants patient, diagnostics, noms des chirurgiens). C'est une
fuite de données de santé ; voir § 10.

## 8. Ergonomie

* Parcours de consultation en **3 étapes** visibles (saisie → prédictions et validation → choix du créneau),
  rien n'est enregistré avant le choix final.
* Chaque prédiction est accompagnée de son incertitude (erreur moyenne sur le jeu de test).
* Propositions sous forme de **cartes comparables** : date, heure, salle, chirurgien, impact sur les autres
  patients (décalés, reprogrammés), lits du jour.
* Code couleur constant : bleu = vacation / hospitalisation, hachures = ambulatoire, rouge = urgence,
  gris = panne ; trait pointillé rouge = maintenant.
* Le chirurgien connecté voit ses vacations surlignées et ses prochaines interventions dès l'accueil.
* Pseudonymes lisibles partout (les identifiants internes `P123` du SMA sont traduits).

## 9. Lancer, tester

```bash
python -m pip install -r interface/requirements.txt
python -m streamlit run interface/app.py          # depuis la racine du dépôt
python -m pytest interface/tests -m "not lent"    # tests rapides
```
Les autres commandes (hybridation, scénarios du SMA, modèles, saturation) sont dans le [README](../README.md).
Au premier lancement : comptes de démonstration dans `interface/donnees/comptes_demo.txt`
(admin, regulation, dr.ct, dr.cl, dr.lz), mot de passe à changer à la première connexion.

## 10. Questions ouvertes (à arbitrer par l'équipe)

1. **Données publiques** : passer le dépôt en privé, purger `donnees_hospitalieres.csv` de l'historique git
   (`git filter-repo`), prévenir l'encadrant / le DPO du fournisseur des données.
2. **Codes praticiens** : le ML connaît 23 codes (BO, CL, CT…), le planning v28 en a d'autres (GHREA,
   DEVOS, DS, DN, TDO/BS) inconnus du modèle → prédictions moins fiables pour eux.
3. **Spécialités réelles** des chirurgiens et spécialités couvertes par l'équipe de garde (aujourd'hui : un seul
   service).
4. **Capacités d'hébergement réelles** (lits, places ambulatoires, réserve).
5. **Niveau 1 sur le planning réel** : quelle grille de créneaux adopter pour ré-optimiser v28 ?
6. **Fusion de `structures_communes.py`** : adopter `commun/` comme unique version ?
7. **Patients à programmer réels** : brancher une vraie file (export du DPI) à la place du générateur.
