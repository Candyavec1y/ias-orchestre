# Commandes exécutées

Commit `d8fbf35abd6e8db531420b6bcaf9b3704957e95a` (branche `nettoyage`). Environnement : `.venv` du dépôt
(Python 3.13.9), voir `environnement.md`. Toutes les commandes se lancent depuis `resultats_rapport/scripts/`.

| Ordre | Commande | Produit | Graines / budgets |
|---|---|---|---|
| 1 | `../../.venv/bin/python a_environnement.py` | `environnement.md`, `donnees_agregees/preparation_controles.md` | — |
| 2 | `../../.venv/bin/python c_ml.py` | `ml_resultats.csv`, `donnees_agregees/ml_*.csv` (dont `temps_ml.csv`), figures `ml_*` | GRAINE_ML = 42 (séparation 80/20 du projet) |
| 3 | `../../.venv/bin/python de_optimisation.py pilote` | `donnees_agregees/pilote/` (pilote, **non utilisé dans les résultats**) | graine 1, budget 2 s |
| 4 | `../../.venv/bin/python de_optimisation.py final` | `n1_resultats.csv`, `n2_resultats.csv`, `donnees_agregees/convergence.json`, `solutions_synthetiques.json`, `campagne_meta.json`, `campagne_de.log` | graines de recherche 1-10 (référence, N1), 1-3 (charges, budgets) ; cohortes 43, 44, 45 ; budget 10 s (2, 5, 20 s pour l'étude de budget) ; ordre des tâches mélangé, graine 2026 ; 4 processus |
| 5 | `../../.venv/bin/python e_analyse.py` | `n1_resume.csv`, `n2_resume.csv`, `gains_contreparties.csv`, `donnees_agregees/n2_tests_confirmatoires.csv`, figures `n1_*`, `n2_*` | — |
| 6 | `../../.venv/bin/python f_ressources.py` | `ressources_resume.csv`, figures `ressources_*` | solutions de la graine 1 |
| 7 | `../../.venv/bin/python g_saturation_robustesse.py` | `robustesse_resultats.csv`, `saturation_resultats.csv`, `donnees_agregees/saturation_courbes.json`, figures | saturation : GRAINE_SATURATION = 42 (+ 43, 44) ; bruit lognormal : graines 1000-1019 |
| 8 | `../../.venv/bin/python h_sma.py` | `sma_scenarios.csv`, `sma_evenements_agreges.csv`, figures `sma_gantt_*` (`h_sma.py gantt` : Gantt seuls) | GRAINE_MESA = 42 ; scénarios aléatoires : graines 1-5 |
| 9 | `../../.venv/bin/python i_temps.py` | `temps.csv`, `donnees_agregees/temps_pour_seuil.csv`, figure `temps_debit_n2` (`temps_resume.md` est rédigé à partir de ces fichiers) | relit les sorties précédentes |
| 10 | `../../.venv/bin/python j_tableaux.py` | `tableaux.tex`, `instances.csv` | — |
| 11 | `../../.venv/bin/python k_figures_sma.py` | figure `sma_strategies` (F11), compléments de `manifest.json` | — |

Les scripts n'écrivent que dans `resultats_rapport/`. Aucun fichier du dépôt (code, CSV, modèles) n'est modifié.

Les fichiers `RESUME.md`, `INTERPRETATION.md`, `ml_resume.md`, `sma_resume.md`, `temps_resume.md`, `parametres.md`,
`PREPARATION_EXPERIENCES.md` et `QUESTIONS.md` sont rédigés à partir des sorties mesurées (aucune valeur saisie
qui ne figure dans un CSV).
