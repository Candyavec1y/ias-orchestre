# OR'CHESTRE — Choix des métaheuristiques (branche v3)

Mesures sur Apple M2, budget en temps réel. Les chiffres viennent des fichiers de ce dossier ; les études retirées
(ML, saturation, robustesse, ressources, temps, tableaux LaTeX, sensibilité des poids) et les anciens documents de
travail restent disponibles dans l'historique git (commit `d06aad8`). *Résultats provisoires : l'équipe refait la fonction de score.*

**Règles de v3** : pendant la recherche, un dépassement de capacité n'est que pénalisé ; chaque méthode propose la
meilleure solution **faisable** rencontrée (tolérance min(5 min, 25 % de la marge de la vacation)) ; les méthodes sont
classées sur le critère qu'elles optimisent, l'**objectif = F2 commun + pénalité de report** (à minimiser).

## Méthodes à utiliser

| Usage | Méthode | Ce qui le justifie | Figure |
|---|---|---|---|
| **Programme opératoire** (N2, recalcul du site, 10 s) | **RS seul** | meilleur objectif (7 702) et meilleur F2 commun ; une solution faisable à chaque exécution ; meilleur à tous les budgets | `n2_scores`, `n2_qualite_budget` |
| Hybridation à présenter pour le N2 | **AGS>RS>TABOU** | deuxième (8 241) ; seule hybridation où l'AGS tourne vraiment (≈ 240 générations) | `n2_scores`, `memetique_comparaisons` (gauche) |
| **Planning des vacations** (N1, instance d'étude) | **RS seul** ou **RS>AGS>TABOU** | les deux atteignent la meilleure valeur observée (900) à chaque graine | `n1_scores`, `n1_convergence` |
| **Réoptimisation globale du SMA** (1 s) | **memetique** | meilleur programme sur 21 scénarios (343 793, contre 354 437 pour AGS>RS>TABOU) ; RS seul n'applique aucun plan en 1 s | `memetique_comparaisons` (droite) |
| **Optimisation locale des salles** (SMA) | **aucune** (règle gloutonne, comme sur le site) | TABOU seul ne change presque rien et double le temps de calcul | `sma_strategies` |

## Figures (`figures/`, PNG 300 dpi)

| Figure | Ce qu'elle montre |
|---|---|
| `n2_scores.png` | Objectif des solutions proposées par méthode (cohorte de référence, 10 graines, 10 s) : RS seul en tête, puis AGS>RS>TABOU |
| `n2_composantes.png` | Composantes de l'objectif N2 : bloc, lits, places et report, par méthode |
| `n2_convergence.png` | Meilleur score de recherche au cours du temps, 10 graines par méthode |
| `n2_qualite_budget.png` | Objectif selon le budget (2, 5, 10, 20 s) : RS seul meilleur à chaque budget |
| `n1_scores.png` | F1 du planning des vacations par méthode (10 graines) |
| `n1_convergence.png` | Convergence N1 |
| `vitesse_convergence.png` | Meilleur score atteint au cours du temps (N1, N2) : TABOU seul démarre le plus vite puis plafonne |
| `memetique_comparaisons.png` | Gauche : memetique contre chaque méthode, graine par graine (N2) ; droite : réoptimisation globale du SMA |
| `sma_strategies.png` | SMA : urgences dans le délai, patients déplacés et temps de calcul selon la stratégie |

## N2 — planning v28, cohorte de référence

421 patients, charge 99 % de la capacité utile, 4 semaines + 3 semaines de report, 10 graines, 10 s. Départ commun
(glouton) : objectif 31 565, non faisable.

| Méthode | Solutions proposées | Objectif F2 + report [IC 95 %] | F2 commun | Patients reportés | Occupation du bloc |
|---|---|---|---|---|---|
| RS seul | 10 / 10 | **7 702** [7 488 ; 7 915] | 3 422 | 23,3 | 92,6 % |
| AGS>RS>TABOU | 10 / 10 | 8 241 [8 092 ; 8 389] | 3 601 | 24,9 | 91,9 % |
| RS>AGS>TABOU | 10 / 10 | 9 153 [8 833 ; 9 473] | 3 893 | 27,5 | 91,0 % |
| memetique | 10 / 10 | 9 584 [9 157 ; 10 010] | 4 014 | 29,1 | 90,5 % |
| TABOU seul | 10 / 10 | 10 580 [10 325 ; 10 834] | 4 000 | 33,9 | 90,5 % |
| AGS seul | 9 / 10 | 22 331 [21 792 ; 22 870] | 6 020 | 70,0 | 84,6 % |

**Tests appariés par graine** (Wilcoxon, Holm ; `donnees_agregees/n2_tests_confirmatoires.csv`) : memetique est moins
bon que RS seul (10 / 10, p = 0,006), meilleur que TABOU seul (9 / 10, p = 0,008) et qu'AGS seul (9 / 9, p = 0,008) ;
AGS>RS>TABOU est moins bon que RS seul (10 / 10, p = 0,002, exploratoire).

**Budget** (objectif, 3 graines) : RS seul 9 157 à 2 s, 8 205 à 5 s, 7 557 à 10 s, 7 251 à 20 s ; AGS>RS>TABOU 10 909,
9 025, 8 069, 7 722 ; memetique 25 155, 11 967, 9 448, 8 130 ; TABOU seul 19 289, 13 243, 10 654, 9 294.

**Rapidité** : TABOU seul est le premier à améliorer le départ (0,04 s en N2 ; RS seul 3,4 s) et atteint son meilleur
score N1 en 0,12 s, mais il plafonne : à 10 s il n'est que cinquième en N2.

## N1 — instance d'étude fictive (8 chirurgiens, 3 salles, 45 blocs de 2 h)

Toutes les méthodes sont faisables (10 graines, 10 s). Départ : F1 = 1 750.

| Méthode | F1 moyen ± écart-type | Meilleur | Gain vs départ |
|---|---|---|---|
| RS seul | 900 ± 0 | 900 | 48,6 % |
| RS>AGS>TABOU | 900 ± 0 | 900 | 48,6 % |
| AGS>RS>TABOU | 925 ± 35 | 900 | 47,1 % |
| memetique | 940 ± 62 | 900 | 46,3 % |
| TABOU seul | 960 ± 32 | 950 | 45,1 % |
| AGS seul | 1 005 ± 50 | 950 | 42,6 % |

## SMA — 21 scénarios déterministes, mêmes événements

| Stratégie | Urgences dans le délai | Décalés | Reportés | Liste d'attente | Temps réel cumulé |
|---|---|---|---|---|---|
| Contract Net seul (site) | 21 / 23 | 26 | 54 | 8 | 6,2 s |
| + optimisation locale TABOU seul | 21 / 23 | 27 | 54 | 8 | 10,8 s |
| + optimisation globale memetique | 21 / 23 | 48 | 49 | 5 | 64,8 s |
| locale + globale | 21 / 23 | 51 | 47 | 4 | 69,3 s |

Réoptimisation globale seule, 1 s (`donnees_agregees/v3_pilote/sma_reoptimisation_globale.csv`) : score du programme
427 110 sans réoptimisation ; **343 793 avec memetique** (14 plans appliqués sur 57) ; 354 437 avec AGS>RS>TABOU (13 sur
57) ; 427 110 avec RS seul (aucun plan appliqué).

## Limites

Une seule instance réelle (planning v28), patients synthétiques, une graine Mesa pour le SMA, fonction de score en
cours de refonte : ces choix sont à revérifier après la refonte du score.

**Point encore ouvert** : dans la semaine de surcharge aléatoire, 3 graines sur 5 font échouer le SMA
(`KeyError: 'chir_7'`, pour toutes les stratégies) : un chirurgien du service sans vacation sur l'horizon de 2
semaines est proposé comme compétent alors qu'aucun agent n'existe pour lui. Ces exécutions sont marquées ÉCHEC dans
`sma_scenarios.csv` (colonne `echec`). Correction à faire : ne proposer que les chirurgiens qui ont un agent.

Commandes pour régénérer ces résultats : section 7 du [README](../README.md).
