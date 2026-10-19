# Tests d'OR'CHESTRE

Depuis la racine du dépôt, avec l'environnement du projet (`.venv`) :

```bash
python -m pytest interface/tests -m "not lent"     # tests rapides (environ 1 min)
python -m pytest interface/tests                   # tout, y compris l'étude de saturation complète
python interface/tests/saturation.py               # étude de saturation détaillée (rapport dans resultats/)
```

Aucun test ne touche `interface/donnees/` : chaque test qui a besoin d'une base en crée une dans un dossier
temporaire (fixture `base_isolee`). Les scénarios du système multi-agent partent d'un programme de test fixe
(glouton commun, 4 semaines à partir du lundi 12/10/2026) : ils sont rapides et toujours identiques.

## Ce qui est testé

| Fichier | Fonctionnalité |
|---|---|
| `test_inscriptions.py` | consultation : propositions sans effet de bord, nouveau patient après les autres, créneau choisi respecté, ordre d'arrivée, confrère refusé / accepté, date au plus tôt, plus de liste d'attente (planning connu sur un an), annulation |
| `test_urgences.py` | aucune urgence refusée même en saturation, délais (urgente, vitale), tous les chirurgiens du service compétents, intervention commencée intouchable, planning de garde, photographie avant / après chaque urgence, alertes horodatées, rejeu déterministe |
| `test_absences.py` | absence d'un chirurgien : vacations fermées, patients replacés avec 2 jours de prévenance, confrère seulement s'il est accepté, consultation et urgence pendant l'absence, retour anticipé, alerte pour un patient prioritaire repoussé |
| `test_pannes.py` | panne du monte-lit : aucun patient hospitalisé brancardé pendant la panne, fin anticipée, fin constatée à l'heure estimée |
| `test_capacites.py` | lits programmables jamais dépassés par une inscription, réserve utilisable par les urgences, capacités réglées par l'administrateur |
| `test_optimisation_globale.py` | programme déjà bon inchangé, plan enregistré rejoué à l'identique, plan devenu invalide refusé avec alerte |
| `test_planning_vacations.py` | parité des semaines, planning d'origine sans conflit, cycle répété sur l'année, détection des conflits, versions datées, identifiants stables des nouveaux praticiens, prise en compte par le SMA, même service pour tous |
| `test_metaheuristiques.py` | AGS et recuit : jamais pires que le départ, niveau 1 sans conflit, score rapide de l'AGS exact, modes de calcul du programme (le mode mémétique est marqué `lent`) |
| `test_ml.py` | données préparées (sans durée de bloc nulle), colonnes des modèles, prédictions cohérentes, codes hors vocabulaire, métriques sur le jeu de test |
| `test_socle.py` | une seule copie des structures communes, chiffrement de la référence dossier, mots de passe, historique scellé, événements |
| `test_interface.py` | connexion, chaque page pour chaque rôle, onglets selon le rôle, déclaration d'une urgence et d'une absence, alerte qui disparaît du bandeau après 10 minutes |
| `test_saturation.py` | sanité de l'étude de saturation sur une semaine (l'étude sur 4 semaines est marquée `lent`) |

## Étude de saturation (`saturation.py`)

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

`resultats/` contient le dernier rapport (`saturation.md`) et la courbe (`saturation_courbe.csv`) ; il n'est pas
versionné.
