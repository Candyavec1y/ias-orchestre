# Tests d'OR'CHESTRE

Depuis la racine du dépôt, avec l'environnement du projet (`.venv`) :

```bash
python -m pytest interface/tests -m "not lent"     # tests rapides (environ 1 min 30)
python -m pytest interface/tests                   # tout, y compris l'étude de saturation complète
python interface/tests/saturation.py               # étude de saturation détaillée (rapport dans resultats/)
python sma/scenarios_sma.py --tous                 # scénarios du système multi-agent (cohérence de chacun)
```

Aucun test ne touche `interface/donnees/` : chaque test qui a besoin d'une base en crée une dans un dossier
temporaire (fixture `base_isolee`). Les scénarios du système multi-agent partent d'un programme de test fixe
(glouton commun, 4 semaines à partir du lundi 12/10/2026) : ils sont rapides et toujours identiques.

## Ce qui est testé

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
| `test_validation.py` | validateur de faisabilité indépendant : chaque type de contrainte violée détecté aux niveaux 1 et 2, programme du site valide pour toutes les méthodes (dont les échanges qui respectent la date au plus tôt), sélection d'une solution faisable, solution non faisable signalée, même départ et même budget pour toutes les méthodes, instance v28 paramétrable |
| `test_reports.py` | semaines de report de l'hybridation : aucune vacation dupliquée, vacations régulières comptées une fois, reports conformes au planning v28, pénalité égale au décalage |
| `test_occupation.py` | convention d'occupation : lit libéré à midi et réutilisable le jour même, jamais deux patients dans un lit ; place ambulatoire par demi-journée, réutilisable l'après-midi après remise en état, deux patients la même demi-journée refusés ; même décompte au niveau 2, dans le SMA, les indicateurs et le validateur |
| `test_ml.py` | préparation commune (sans durée de bloc nulle), règle d'urgence unique, découpage unique 80/20, colonnes des modèles, prédictions cohérentes, codes hors vocabulaire, métriques sur le jeu de test |
| `test_socle.py` | une seule copie des structures communes, chiffrement de la référence dossier, mots de passe, historique scellé, événements |
| `test_interface.py` | connexion, chaque page pour chaque rôle, onglets selon le rôle, déclaration d'une urgence (rien n'est placé avant « Valider le placement », annulation possible), d'une absence, d'une prolongation d'intervention et de lits indisponibles, alertes du SMA dans l'onglet « Alertes » (plus de bandeau rouge), marquées « nouvelle » pendant 10 minutes |
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
