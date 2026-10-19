# OR'CHESTRE — choix de conception de l'interface

Ce document explique les décisions prises pour construire l'interface d'aide à la décision à partir
du dépôt `ias-orchestre`. Les points qui demandent un arbitrage de l'équipe sont regroupés à la fin
(§ 10, « Questions ouvertes »).

---

## 1. Technologie : Streamlit, 100 % Python

* Le dépôt contenait déjà deux maquettes Streamlit (`app.py`, `app_chirurgien.py`). Je les ai reprises
  comme point de départ (parcours « ajouter un patient → propositions → choix », grille des vacations,
  validation des codes CIM-10 / CCAM par expressions régulières) au lieu d'introduire un autre framework.
* Navigation multipage native (`st.navigation`), graphiques Plotly (Gantt interactif au survol),
  base SQLite locale (aucun serveur à installer).
* Les deux maquettes d'origine ne sont pas modifiées ; la nouvelle interface est dans `interface/`.

```
interface/
├── app.py                 point d'entrée : connexion, rôles, navigation
├── orchestre/             NOYAU sans interface graphique (testable)
│   ├── chemins.py         accès aux dossiers du dépôt (sys.path), commun/ en premier
│   ├── ml.py              modèles .joblib, vocabulaires, prédiction, validation 80/20
│   ├── programme.py       planning v28, niveau 1, programme niveau 2 (hybridations)
│   ├── sma_service.py     rejeu des événements dans le SMA, inscription, annulation
│   └── stockage.py        SQLite, chiffrement, comptes, traces, purge RGPD
├── vues/                  une page par onglet + graphiques
├── tests/                 tests du noyau (pytest)
└── donnees/               base locale, clé, caches — créé au lancement, ignoré par git
commun/structures_communes.py   version FUSIONNÉE des classes communes (voir § 2)
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
 Consultation ──► ML (5 modèles) ──► validation par le chirurgien ──┐
                                                                    ▼
 Planning v28 (vacations fixes) ──► Métaheuristiques / hybridation ──► Programme initial
                                    (patients → vacations, niveau 2)        │
                                                                            ▼
 Urgences, pannes, annulations, nouvelles inscriptions ──► SMA (Mesa) ──► Programme courant
```

## 4. Onglet Consultation (machine learning)

* **Entrées demandées = exactement les 11 variables des modèles** (`CAT_COLS + NUM_COLS` de
  `modele_prediction_rapide.py`) : type d'intervention, CIM-10 principal, CCAM 1, sexe, praticien,
  type d'anesthésie, anesthésie loco-régionale, âge, année, mois, jour de la semaine.
  * année / mois / jour de semaine sont **déduits de la date « opérable au plus tôt »** (les modèles ont
    appris sur la date d'intervention ; `creation_patients.py` utilisait la date du jour, ce qui biaise
    ces trois variables).
  * listes déroulantes = **modalités vues à l'entraînement**, lues dans l'encodeur interne du modèle,
    avec saisie libre possible ; une valeur inconnue du modèle déclenche un avertissement.
* **Non collectés** (minimisation) : nom, prénom, date de naissance (l'âge suffit), CIM associés 1-5 et
  CCAM 2-4 (présents dans `creation_patients.py` mais **inutilisés** par les modèles).
* **Modèles utilisés** : ceux du dépôt (`machine_learning/outputs/models_rapide/*.joblib`), appelés via
  `predire_patient()` de `utilisation_modèle.py`. La qualité affichée vient du protocole
  **80 % entraînement / 20 % test** (`valider_sur_jeu_de_test`), recalculée par l'interface ; seules des
  métriques agrégées sont conservées (`donnees/metriques_ml.json`).
* **Score d'urgence 1-10 → priorité 1-4** des structures communes : 1-2 → 1, 3-4 → 2, 5-7 → 3, 8-10 → 4.
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
  le niveau 1 sur l'**instance d'étude commune** (8 chirurgiens, 3 salles) et affiche le planning obtenu.
  Brancher le N1 sur v28 demande de définir une grille de créneaux
  (question ouverte § 10).
* **Programme initial fictif** : le dépôt ne contient pas de liste de patients à programmer. J'utilise le
  générateur commun `generer_patients_etude` (patients `DEMO-xxxx`) sur un **horizon de 4 semaines**, avec
  une charge décroissante (85-100 %, 60-75 %, 35-50 %, 10-25 % des heures de vacation) : un programme se
  remplit à l'approche de la date, et il reste de la place pour les nouvelles consultations.
* **Hébergement** : les capacités de l'étude (14 lits dont 2 de réserve, 10 places) sont calibrées pour
  8 chirurgiens ; avec la vingtaine de praticiens et 4 salles de v28, 45 patients restaient non placés.
  J'ai retenu **30 lits (dont 3 de réserve) et 20 places ambulatoires** (pic observé : 25 lits). À
  remplacer par les capacités réelles (question ouverte).

## 6. Onglet Urgences (système multi-agent)

* **Le SMA du dépôt est utilisé tel quel** (`sma/sma_urgences.py`, Mesa, agents Triage, Régulation, Salle,
  Chirurgien, Hébergement, Logistique, protocole Contract Net). L'interface permet de déclarer une
  urgence (gravité vitale / urgente / différable), une panne, une prolongation ou une fin de panne du
  monte-lit, et affiche décisions, alertes, Gantt de la journée et messages FIPA-ACL.
* **Approche événementielle (« event sourcing »)** : la base ne stocke que le programme initial et la liste
  des événements ; l'état du bloc est obtenu en **rejouant** les événements dans un modèle Mesa neuf
  jusqu'à l'heure courante (≈ 0,5 s). Avantages : état reproductible et vérifiable
  (`verifier_coherence()`), historique complet pour la traçabilité, et l'effacement d'un patient (RGPD) se
  propage naturellement (on retire ses événements et on rejoue).
* **Insertion des patients de consultation** (le SMA d'origine ne gérait que les urgences et les pannes) :
  j'ai ajouté, **sans modifier les agents**, un événement « inscription » qui réutilise l'appel d'offres
  `cfp_replacement` de l'agent de Régulation ; les agents Chirurgien et Hébergement valident chaque
  proposition. Les 4 meilleures (une par créneau) sont **présentées au chirurgien, qui choisit**. Au
  rejeu, le créneau choisi est réappliqué ; s'il n'est plus possible, la meilleure alternative est prise ;
  sinon le patient va en liste d'attente (relancée chaque matin à 7 h par la Régulation).
* **Annulation** : un événement libère le créneau et la Régulation relance la liste d'attente.
* Correctif côté interface : pour un patient de consultation, l'heure « initiale » de référence est celle
  de son **premier placement** (sinon le bilan du SMA le comptait comme « décalé » depuis minuit).
* Une urgence est enregistrée **à l'heure courante** (pas de saisie rétroactive, qui réécrirait l'histoire).
* **Horloge** : temps réel (Europe/Paris) par défaut ; l'administrateur peut figer une **heure de
  démonstration** et l'avancer (+30 min, +2 h, lendemain 7 h 30) pour montrer le SMA en action.
* Spécialités : le SMA ne connaît que 5 spécialités (`SPECIALITES_V28`, hypothèse du jeu de test). Hors de
  ces 5 chirurgiens, un patient ne peut pas être « repris par un confrère ».

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
pip install -r interface/requirements.txt
streamlit run interface/app.py            # depuis la racine du dépôt
python -m pytest interface/tests -q       # tests du noyau
```
Au premier lancement : comptes de démonstration dans `interface/donnees/comptes_demo.txt`
(admin, regulation, dr.ct, dr.cl, dr.lz), mot de passe à changer à la première connexion.

## 10. Questions ouvertes (à arbitrer par l'équipe)

1. **Données publiques** : passer le dépôt en privé, purger `donnees_hospitalieres.csv` de l'historique git
   (`git filter-repo`), prévenir l'encadrant / le DPO du fournisseur des données.
2. **Codes praticiens** : le ML connaît 23 codes (BO, CL, CT…), le planning v28 en a d'autres (GHREA,
   DEVOS, DS, DN, TDO/BS) inconnus du modèle → prédictions moins fiables pour eux.
3. **Spécialités réelles** des chirurgiens (le SMA n'en connaît que 5, par hypothèse).
4. **Capacités d'hébergement réelles** (lits, places ambulatoires, réserve).
5. **Niveau 1 sur le planning réel** : quelle grille de créneaux adopter pour ré-optimiser v28 ?
6. **Fusion de `structures_communes.py`** : adopter `commun/` comme unique version ?
7. **Patients à programmer réels** : brancher une vraie file (export du DPI) à la place du générateur.
