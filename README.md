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

## 5. Tests et commandes

Toujours depuis la racine, environnement activé :

```bash
python -m pytest interface/tests -m "not lent"     # tests rapides (environ 1 min 30)
python -m pytest interface/tests                   # tous les tests
python interface/tests/saturation.py               # étude : combien de patients pour saturer le bloc ?

python metaheuristiques/hybridation.py --help                                 # options de l'hybridation
python metaheuristiques/hybridation.py                                        # niveau 2 sur le planning v28
python metaheuristiques/hybridation.py --instance etude                       # niveaux 1 et 2, instance d'étude
python metaheuristiques/hybridation.py --semaines 4 --temps 20 --graines 1 2 3   # campagne sur plusieurs graines

python sma/scenarios_sma.py --liste                # scénarios du système multi-agent
python sma/scenarios_sma.py insertion_simple       # un scénario (--messages : messages entre agents)
python sma/scenarios_sma.py --tous                 # tous les scénarios, tableau récapitulatif

python machine_learning/modele_prediction_rapide.py --evaluer-seulement     # métriques, sans réécrire les modèles

python metaheuristiques/sensibilite_poids.py       # sensibilité des poids du score N2 (≈ 3 min)
python sma/sma_sensibilite.py                      # sensibilité des coefficients du SMA
```

Toutes les commandes acceptent `--graine` ; capacités, budget, graines et horizons par défaut sont dans
[`commun/parametres.py`](commun/parametres.py). Détail des tests et de l'étude de saturation :
[interface/tests/README.md](interface/tests/README.md).

---

## 6. En cas de problème

| Symptôme | Solution |
|---|---|
| `bad interpreter` ou `streamlit: command not found` | Utiliser `python -m streamlit run interface/app.py` (et non `streamlit run`), environnement activé. Si le dossier du projet a été déplacé ou renommé, recréer `.venv` (étape 2). |
| `ModuleNotFoundError: No module named '…'` | Environnement non activé, ou dépendances incomplètes : relancer `python -m pip install -r interface/requirements.txt`. |
| Windows : « l'exécution de scripts est désactivée » à l'activation | Exécuter une fois `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis réactiver. |
| `Port 8501 is already in use` | Le site tourne déjà dans un autre terminal, ou lancer sur un autre port : `python -m streamlit run interface/app.py --server.port 8502`. |
| Le site s'affiche sans couleurs ni logo | Il a été lancé hors de la racine du dépôt : revenir dans `ias-orchestre/` et relancer. |
| Mot de passe perdu | L'admin peut désactiver le compte et en créer un nouveau (Administration → Comptes). Sur une installation de test uniquement : supprimer `interface/donnees/` recrée tout au prochain lancement, **en effaçant patients, historique et comptes**. |

---

## 7. Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `interface/` | l'application web (`app.py`), ses pages (`vues/`), sa logique (`orchestre/`) et ses tests (`tests/`) |
| `machine_learning/` | données historiques, préparation et évaluation communes (`preparation.py`), entraînement (`modele_prediction_rapide.py`), utilisation (`utilisation_modele.py`) et les 4 modèles (`outputs/models_rapide/`) |
| `metaheuristiques/` | hybridation AGS + recuit simulé + recherche taboue (`hybridation.py`, seule implémentation de chaque algorithme) et format des résultats (`sorties.py`) |
| `planning_vacations/` | planning réel des vacations des chirurgiens (`planning_vacations_v28.py`, cycle de 4 semaines) |
| `sma/` | système multi-agent de gestion des urgences et des aléas (`sma_urgences.py`, Mesa), scénarios (`scenarios_sma.py`), optimisation globale (`optimisation_sma.py`, `metaheuristiques_sma.py`) |
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
* Chaque programme est contrôlé par un **validateur de faisabilité** indépendant ; les contraintes violées sont
  affichées.
* **Aléas** gérés par le SMA : urgences (avec transfert proposé, jamais décidé seul), pannes du monte-lit,
  absences de chirurgien, prolongations d'intervention, lits indisponibles, annulations.

Les choix de conception sont détaillés dans [`interface/CHOIX.md`](interface/CHOIX.md).
