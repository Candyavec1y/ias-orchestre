# OR'CHESTRE — aide à la décision pour le bloc opératoire

Application web (Python / Streamlit) qui construit le programme opératoire, prédit la durée et la prise
en charge des patients, insère les urgences en temps réel et trace toutes les décisions.

---

## 1. Ce qu'il faut installer

| Outil | Version | Où le trouver |
|---|---|---|
| **Python** | 3.11 ou plus récent (testé avec 3.13 et 3.14) | <https://www.python.org/downloads/> — sous Windows, cocher **« Add python.exe to PATH »** pendant l'installation |
| **Git** | n'importe quelle version récente | <https://git-scm.com/downloads> |

Vérifier dans un terminal :

```bash
python3 --version     # Windows : python --version
git --version
```

Toutes les bibliothèques Python (Streamlit, scikit-learn, Mesa, Plotly…) sont listées dans
[`interface/requirements.txt`](interface/requirements.txt) et s'installent en une commande (étape 2).

---

## 2. Installation (une seule fois)

### macOS / Linux

```bash
git clone <adresse-du-dépôt> ias-orchestre
cd ias-orchestre
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r interface/requirements.txt
```

### Windows (PowerShell)

```powershell
git clone <adresse-du-dépôt> ias-orchestre
cd ias-orchestre
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r interface\requirements.txt
```

L'installation prend environ une minute. Le dossier `.venv/` contient l'environnement Python du projet :
il est propre à chaque ordinateur et n'est pas versionné.

---

## 3. Lancer le site

À chaque utilisation, **depuis le dossier racine `ias-orchestre/`** :

```bash
source .venv/bin/activate            # Windows : .venv\Scripts\Activate.ps1
python -m streamlit run interface/app.py
```

Le site s'ouvre sur **<http://localhost:8501>**. Pour l'arrêter : `Ctrl + C` dans le terminal.

> Lancez bien depuis la racine : c'est là que se trouve `.streamlit/config.toml` (couleurs, polices,
> sécurité). Lancé depuis un autre dossier, le site fonctionne mais sans sa charte graphique.

---

## 4. Premier lancement et comptes

Au premier démarrage, l'application :

1. crée le dossier `interface/donnees/` : base de données, clés de chiffrement et de scellement de
   l'historique, et le fichier **`interface/donnees/comptes_demo.txt`** qui contient les identifiants et
   mots de passe provisoires ;
2. calcule le programme opératoire de la semaine en cours (une dizaine de secondes).

| Identifiant | Rôle | Ce que voit le compte |
|---|---|---|
| `admin` | Administrateur | tableau de bord, historique, comptes, horloge, et tout le reste |
| `regulation` | Cadre de bloc / régulation | programme de toutes les salles, tous les patients, urgences |
| `dr.ct`, `dr.cl`, `dr.lz` | Chirurgien | son planning du jour, ses patients, consultation |

Chaque mot de passe provisoire doit être changé à la première connexion (12 caractères minimum avec
minuscule, majuscule, chiffre et caractère spécial). D'autres comptes nominatifs se créent depuis
**Administration → Comptes**.

**Ne jamais versionner ni partager `interface/donnees/`** : il contient la base patients et les clés.
Il est exclu de git ; chaque installation a donc ses propres comptes et ses propres données.

### Démonstration

Connecté en `admin` : **Administration → Horloge** permet de fixer l'heure de l'application (par
exemple mardi 9 h 00) pour rejouer une journée, puis **Urgences** pour déclarer une urgence ou une panne
du monte-lit.

---

## 5. Le site : pages et organisation du code

| Page | Comptes | Brique du dépôt | Rôle |
|---|---|---|---|
| **Tableau de bord** | admin | — | lits et places occupés, occupation du bloc, état des salles, tendances, qualité de service |
| **Historique** | admin | — | journal horodaté, en ajout seul et scellé, de toutes les actions et des déplacements de patients |
| **Accueil** | chirurgien, cadre de bloc | `metaheuristiques/`, `sma/` | chirurgien : son planning et ses patients du jour ; cadre de bloc : programme de toutes les salles |
| **Consultation** | tous | `machine_learning/` (HistGradientBoosting) | saisie de la consultation, prédictions (prise en charge, durée, nuits), priorité proposée par la règle d'urgence (non validée cliniquement), validation par le médecin, choix du créneau |
| **Planning** | tous | `planning_vacations/planning_vacations_v28.py`, `metaheuristiques/hybridation.py` | vacations de la semaine, programme opératoire du jour (Gantt), occupation anonyme des salles |
| **Urgences** | tous | `sma/sma_urgences.py` (Mesa) | déclarer une urgence (placement proposé par le SMA, puis « Valider le placement »), une panne du monte-lit, la prolongation d'une intervention, des lits indisponibles (cadre de bloc, admin), une absence ; onglet Alertes ; suivi des urgences et transferts proposés ; fil des décisions et messages entre agents (admin) |
| **Patients** | tous (chirurgien : ses patients) | — | statut, annulation, export et effacement (RGPD) |
| **Administration** | admin | — | comptes, planning des vacations, lits et places, optimisation globale, horloge de démonstration |
| **Confidentialité** | tous | — | notice d'information patient, mesures RGPD / CNIL |

* `app.py` : connexion, barre latérale et navigation selon le rôle.
* `vues/` : une page par fichier ; `commun.py` (charte graphique, session, historique), `graphiques.py` (Plotly).
* `orchestre/` : `ml.py` (prédictions), `programme.py` (métaheuristiques), `sma_service.py` (système
  multi-agent), `stockage.py` (SQLite, chiffrement, historique scellé), `chemins.py` (accès au dépôt),
  `libelles_codes.json` (libellés officiels CIM-10 / CCAM).
* `donnees/` : créé au premier lancement (base, clés, comptes de démonstration) ; **jamais versionné**.

Les choix de conception (données, RGPD, ergonomie, questions ouvertes) sont détaillés dans
[`interface/CHOIX.md`](interface/CHOIX.md).

---

## 6. Tests

Toujours depuis la racine, environnement activé :

```bash
python -m pytest interface/tests -m "not lent"     # tests rapides (environ 1 min 30)
python -m pytest interface/tests                   # tous les tests, y compris l'étude de saturation complète
python sma/scenarios_sma.py --tous                 # scénarios du système multi-agent (cohérence de chacun)
```

Aucun test ne touche `interface/donnees/` : chaque test qui a besoin d'une base en crée une dans un dossier
temporaire (fixture `base_isolee`). Les scénarios du système multi-agent partent d'un programme de test fixe
(glouton commun, 4 semaines à partir du lundi 12/10/2026) : ils sont rapides et toujours identiques.

| Fichier | Fonctionnalité |
|---|---|
| `test_inscriptions.py` | consultation : propositions sans effet de bord, nouveau patient après les autres, créneau choisi respecté, ordre d'arrivée, confrère refusé / accepté, date au plus tôt, plus de liste d'attente (planning connu sur un an), annulation |
| `test_urgences.py` | aucune urgence laissée sans prise en charge même en saturation, délais (urgente, vitale), tous les chirurgiens du service compétents, intervention commencée intouchable, planning de garde, photographie avant / après chaque urgence, alertes horodatées, rejeu déterministe |
| `test_absences.py` | absence d'un chirurgien (événement du SMA) : vacations fermées, patients replacés avec 2 jours de prévenance, confrère seulement s'il est accepté, consultation et urgence pendant l'absence, retour anticipé, alerte pour un patient prioritaire repoussé |
| `test_aleas_sma.py` | prolongation d'une intervention (décalage simple, dépassement du créneau avec replacement, pendant une panne) ; lits indisponibles (capacité jamais dépassée, retour à la normale, faible priorité déplacée d'abord, réserve gardée pour les urgences) ; transfert proposé pour une spécialité non couverte, comportement inchangé sinon |
| `test_pannes.py` | panne du monte-lit : aucun patient hospitalisé brancardé pendant la panne, fin anticipée, fin constatée à l'heure estimée |
| `test_capacites.py` | lits programmables jamais dépassés par une inscription, réserve utilisable par les urgences, capacités réglées par l'administrateur |
| `test_optimisation_globale.py` | programme déjà bon inchangé, plan enregistré rejoué à l'identique, plan devenu invalide refusé avec alerte |
| `test_planning_vacations.py` | parité des semaines, planning d'origine sans conflit, cycle répété sur l'année, détection des conflits, versions datées, identifiants stables des nouveaux praticiens, prise en compte par le SMA, même service pour tous |
| `test_metaheuristiques.py` | RS, Tabou et AGS seuls (modes de `hybridation.py`) : jamais pires que le départ, niveau 1 sans conflit, score incrémental égal au score complet, modes de calcul du programme (le mode mémétique est marqué `lent`) |
| `test_validation.py` | validateur de faisabilité indépendant : chaque type de contrainte violée détecté aux niveaux 1 et 2, tolérance de dépassement des vacations (même jugement que l'état incrémental), solution proposée = meilleure solution faisable rencontrée, programme du site valide pour toutes les méthodes (dont les échanges qui respectent la date au plus tôt), sélection d'une solution faisable, solution non faisable signalée, même départ et même budget pour toutes les méthodes, instance v28 paramétrable |
| `test_reports.py` | semaines de report de l'hybridation : aucune vacation dupliquée, vacations régulières comptées une fois, reports conformes au planning v28, pénalité égale au décalage |
| `test_occupation.py` | convention d'occupation : lit libéré à midi et réutilisable le jour même, jamais deux patients dans un lit ; place ambulatoire par demi-journée, réutilisable l'après-midi après remise en état, deux patients la même demi-journée refusés ; même décompte au niveau 2, dans le SMA, les indicateurs et le validateur |
| `test_ml.py` | préparation commune (sans durée de bloc nulle), règle d'urgence unique, découpage unique 80/20, colonnes des modèles, prédictions cohérentes, codes hors vocabulaire, métriques sur le jeu de test |
| `test_socle.py` | une seule copie des structures communes, chiffrement de la référence dossier, mots de passe, historique scellé, événements |
| `test_interface.py` | connexion, chaque page pour chaque rôle, onglets selon le rôle, déclaration d'une urgence (rien n'est placé avant « Valider le placement », annulation possible), d'une absence, d'une prolongation d'intervention et de lits indisponibles, alertes du SMA dans l'onglet « Alertes » (plus de bandeau rouge), marquées « nouvelle » pendant 10 minutes |
| `test_saturation.py` | sanité de l'étude de saturation sur une semaine (l'étude sur 4 semaines est marquée `lent`) |

### Étude de saturation (`interface/tests/saturation.py`)

Combien de patients faut-il pour remplir le bloc ? Le programme part **vide** (planning réel des vacations,
capacités du site) ; des patients au profil **réel** (durées et séjours tirés des 14 477 séjours des données
hospitalières, chirurgien au prorata de son temps de vacation) sont inscrits un par un et placés par le SMA comme
sur le site. Le rapport donne la capacité de l'horizon, la courbe d'occupation, les patients nécessaires pour
remplir 50 / 80 / 90 % de la capacité utile, et la **ressource limitante**, mesurée en rejouant l'étude avec des
lits puis des places illimités.

```bash
python interface/tests/saturation.py --semaines 4                      # capacités du site
python interface/tests/saturation.py --lits 42 --reserve 4 --places 18  # autres capacités
python interface/tests/saturation.py --confrere                         # patients acceptant un confrère
```

Le rapport (`saturation.md`) et la courbe (`saturation_courbe.csv`) sont écrits dans `interface/tests/resultats/`,
non versionné.

---

## 7. Commandes de recherche et résultats

```bash
python metaheuristiques/hybridation.py --help                                 # options de l'hybridation
python metaheuristiques/hybridation.py                                        # niveau 2 sur le planning v28
python metaheuristiques/hybridation.py --instance etude                       # niveaux 1 et 2, instance d'étude
python metaheuristiques/hybridation.py --semaines 4 --temps 20 --graines 1 2 3   # campagne sur plusieurs graines

python sma/scenarios_sma.py --liste                # scénarios du système multi-agent
python sma/scenarios_sma.py insertion_simple       # un scénario (--messages : messages entre agents)

python machine_learning/modele_prediction_rapide.py --evaluer-seulement     # métriques, sans réécrire les modèles

python metaheuristiques/sensibilite_poids.py       # sensibilité des poids du score N2 (≈ 8 min)
python sma/sma_sensibilite.py                      # sensibilité des coefficients du SMA
```

Toutes les commandes acceptent `--graine` ; capacités, budget, graines et horizons par défaut sont dans
[`commun/parametres.py`](commun/parametres.py).

**Résultats du rapport** : [`resultats_rapport/RESUME.md`](resultats_rapport/RESUME.md) (méthodes retenues, chiffres,
figures). Pour les régénérer, depuis `resultats_rapport/scripts/` :

| Commande | Produit | Durée |
|---|---|---|
| `../../.venv/bin/python de_optimisation.py final` | campagne N1 / N2 : `n1_resultats.csv`, `n2_resultats.csv`, `donnees_agregees/convergence.json` (graines 1-10, cohortes 43-45, charges 70-115 %, budgets 2-20 s) | ≈ 17 min |
| `../../.venv/bin/python e_analyse.py` | résumés N1 / N2, tests de Wilcoxon, figures `n1_*` et `n2_*` | < 1 min |
| `../../.venv/bin/python h_sma.py` puis `k_figures_sma.py` | scénarios du SMA par stratégie (`sma_scenarios.csv`), figure `sma_strategies` | ≈ 7 min |
| `../../.venv/bin/python sma_globale.py` | réoptimisation globale du SMA : memetique, AGS>RS>TABOU, RS seul | ≈ 4 min |
| `../../.venv/bin/python pilote_memetique_rs.py` | pilote du mémétique poli par un RS court | ≈ 5 min |
| `../../.venv/bin/python l_figures_messages.py` | figures `vitesse_convergence` et `memetique_comparaisons` | < 1 min |

Les scripts n'écrivent que dans `resultats_rapport/` ; les budgets étant en temps réel, une nouvelle exécution donne
des chiffres légèrement différents.

---

## 8. En cas de problème

| Symptôme | Solution |
|---|---|
| `bad interpreter` ou `streamlit: command not found` | Utiliser `python -m streamlit run interface/app.py` (et non `streamlit run`), environnement activé. Si le dossier du projet a été déplacé ou renommé, recréer `.venv` (étape 2). |
| `ModuleNotFoundError: No module named '…'` | Environnement non activé, ou dépendances incomplètes : relancer `python -m pip install -r interface/requirements.txt`. |
| Windows : « l'exécution de scripts est désactivée » à l'activation | Exécuter une fois `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis réactiver. |
| `Port 8501 is already in use` | Le site tourne déjà dans un autre terminal, ou lancer sur un autre port : `python -m streamlit run interface/app.py --server.port 8502`. |
| Le site s'affiche sans couleurs ni logo | Il a été lancé hors de la racine du dépôt : revenir dans `ias-orchestre/` et relancer. |
| Mot de passe perdu | L'admin peut désactiver le compte et en créer un nouveau (Administration → Comptes). Sur une installation de test uniquement : supprimer `interface/donnees/` recrée tout au prochain lancement, **en effaçant patients, historique et comptes**. |

---

## 9. Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `interface/` | l'application web (`app.py`), ses pages (`vues/`), sa logique (`orchestre/`) et ses tests (`tests/`) |
| `machine_learning/` | données historiques, préparation et évaluation communes (`preparation.py`), entraînement (`modele_prediction_rapide.py`), utilisation (`utilisation_modele.py`) et les 4 modèles (`outputs/models_rapide/`) |
| `metaheuristiques/` | hybridation AGS + recuit simulé + recherche taboue (`hybridation.py`, seule implémentation de chaque algorithme), format des résultats (`sorties.py`), sensibilité des poids du score (`sensibilite_poids.py`) |
| `planning_vacations/` | planning réel des vacations des chirurgiens (`planning_vacations_v28.py`, cycle de 4 semaines) |
| `sma/` | système multi-agent de gestion des urgences et des aléas (`sma_urgences.py`, Mesa), scénarios (`scenarios_sma.py`), optimisation globale (`optimisation_sma.py`, `metaheuristiques_sma.py`), sensibilité des coefficients (`sma_sensibilite.py`) |
| `resultats_rapport/` | résultats du rapport : `RESUME.md`, figures (PNG), données agrégées, scripts de campagne (`scripts/`), paramètres (`parametres.md`) |
| `commun/` | paramètres partagés (`parametres.py`), structures de données communes (`structures_communes.py`), validateur de faisabilité (`validation.py`) |

### En bref

* **Niveau 1** (chirurgiens → plages) : étudié sur une instance d'étude fictive ; **niveau 2** (patients →
  vacations) et **SMA** : sur le planning réel v28.
* **Capacités du site** : 30 lits dont 3 de réserve pour les urgences, 20 places ambulatoires (modifiables par
  l'administrateur) ; l'instance d'étude du niveau 1 a ses propres capacités (14 / 2 / 10).
* **Lits** comptés par nuitée, sortie à midi ; **places ambulatoires** comptées par demi-journée (matin /
  après-midi) ; 1 h de remise en état entre deux patients d'un lit ou d'une place.
* **Priorité proposée** en consultation : règle du projet (CIM-10 / CCAM), non validée cliniquement, que le
  médecin valide ou corrige ; les durées et nuits sont prédites par les modèles.
* Chaque programme est contrôlé par un **validateur de faisabilité** indépendant (tolérance de dépassement d'une
  vacation : min(5 min, 25 % de sa marge)) ; chaque métaheuristique propose la meilleure solution faisable rencontrée.
* **Méthodes retenues** (`resultats_rapport/RESUME.md`) : RS seul pour le programme opératoire, AGS>RS>TABOU comme
  hybridation de référence, RS seul ou RS>AGS>TABOU pour le planning des vacations, mémétique pour la réoptimisation
  globale du SMA (à la demande sur le site), aucune optimisation locale des salles.
* **Aléas** gérés par le SMA : urgences (avec transfert proposé, jamais décidé seul), pannes du monte-lit,
  absences de chirurgien, prolongations d'intervention, lits indisponibles, annulations.
