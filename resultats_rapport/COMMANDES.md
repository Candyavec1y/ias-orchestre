# Commandes

Branche `v3`, environnement `.venv` du dépôt (voir `environnement.md`). Depuis `resultats_rapport/scripts/` :

| Commande | Produit | Durée |
|---|---|---|
| `../../.venv/bin/python de_optimisation.py final` | `n1_resultats.csv`, `n2_resultats.csv`, `donnees_agregees/convergence.json`, `campagne_meta.json` (graines 1-10, cohortes 43-45, charges 70-115 %, budgets 2-20 s, 4 processus) | ≈ 17 min |
| `../../.venv/bin/python e_analyse.py` | `n1_resume.csv`, `n2_resume.csv`, `donnees_agregees/n2_tests_confirmatoires.csv`, figures `n1_scores`, `n1_convergence`, `n2_scores`, `n2_composantes`, `n2_convergence`, `n2_qualite_budget` | < 1 min |
| `../../.venv/bin/python h_sma.py` | `sma_scenarios.csv` (21 scénarios + 2 aléatoires × 5 graines, 4 stratégies) | ≈ 7 min |
| `../../.venv/bin/python k_figures_sma.py` | figure `sma_strategies` | < 1 min |
| `../../.venv/bin/python sma_globale.py` | `donnees_agregees/v3_pilote/sma_reoptimisation_globale.csv` (réoptimisation globale : memetique, AGS>RS>TABOU, RS seul) | ≈ 4 min |
| `../../.venv/bin/python pilote_memetique_rs.py` | `donnees_agregees/v3_pilote/pilote_memetique_rs*.csv` (mémétique poli par RS court) | ≈ 5 min |
| `../../.venv/bin/python l_figures_messages.py` | figures `vitesse_convergence`, `memetique_comparaisons` | < 1 min |

Les scripts n'écrivent que dans `resultats_rapport/` et ne modifient aucun fichier du projet. Les budgets étant en
temps réel, une nouvelle exécution donne des chiffres légèrement différents.
