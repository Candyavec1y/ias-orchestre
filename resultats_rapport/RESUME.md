# OR'CHESTRE — Résultats et choix des métaheuristiques (branche v3)

Mesures sur Apple M2, budget en temps réel ; toutes les simulations ont été relancées avec le code de la branche v3.
Les chiffres viennent des fichiers de ce dossier. *Résultats provisoires : l'équipe refait la fonction de score et
revoit le ML.*

**Règles de v3** : pendant la recherche, un dépassement de capacité n'est que pénalisé ; chaque méthode propose la
meilleure solution **faisable** rencontrée (tolérance min(5 min, 25 % de la marge de la vacation)) ; les méthodes sont
classées sur le critère qu'elles optimisent, l'**objectif = F2 commun + pénalité de report** (à minimiser).

## Méthodes à utiliser

| Usage | Méthode | Ce qui le justifie | Figure |
|---|---|---|---|
| **Programme opératoire** (N2, recalcul du site, 10 s) | **RS seul** | meilleur objectif (7 714) et meilleur F2 commun ; une solution faisable à chaque exécution ; meilleur à tous les budgets | `n2_scores`, `n2_qualite_budget` |
| Hybridation à présenter pour le N2 | **AGS>RS>TABOU** | deuxième (8 352) ; seule hybridation où l'AGS tourne vraiment | `n2_scores`, `memetique_comparaisons` (gauche) |
| **Planning des vacations** (N1, instance d'étude) | **RS seul** ou **RS>AGS>TABOU** | les deux atteignent la meilleure valeur observée (900) à chaque graine | `n1_scores`, `n1_convergence` |
| **Réoptimisation globale du SMA** (1 s) | **memetique** | meilleur programme sur 21 scénarios (343 793, contre 349 887 pour AGS>RS>TABOU) ; RS seul n'applique aucun plan en 1 s | `memetique_comparaisons` (droite) |
| **Optimisation locale des salles** (SMA) | **aucune** (règle gloutonne, comme sur le site) | TABOU seul ne change presque rien et double le temps de calcul | `sma_strategies` |

## Figures (`figures/`, PNG 300 dpi)

| Thème | Figures |
|---|---|
| Machine learning | `ml_reel_predit` (réel vs prédit, densités), `ml_residus_confusion` (résidus de la durée, matrice de confusion), `ml_calibration` (probabilité « ambulatoire ») |
| Niveau 1 | `n1_scores`, `n1_convergence`, `n1_gantt` (planning faisable de meilleur score) |
| Niveau 2 | `n2_scores`, `n2_composantes` (bloc, lits, places, report), `n2_convergence`, `n2_qualite_budget`, `n2_charges` (solutions proposées et reports selon la charge), `n2_delai_priorite` |
| Méthodes | `vitesse_convergence` (TABOU seul démarre le plus vite puis plafonne), `memetique_comparaisons` (memetique graine par graine en N2 ; réoptimisation globale du SMA), `temps_debit_n2` |
| Ressources | `ressources_profils` (bloc, lits, places sur 4 semaines + report), `ressources_lits_rotation` (sorties à midi, admissions), `ressources_compromis` (occupation du bloc vs pic de lits) |
| Saturation et robustesse | `saturation_courbes`, `robustesse_durees` (heures supplémentaires et faisabilité après perturbation des durées) |
| SMA | `sma_strategies`, `sma_sensibilite_affectations` et `sma_sensibilite_perturbes` (coefficients × 0,5 et × 2), 10 Gantt avant / après `sma_gantt_*` (urgence + panne, journée surchargée, prolongation, lits indisponibles) |

## N2 — planning v28, cohorte de référence

421 patients, charge 99 % de la capacité utile, 4 semaines + 3 semaines de report, 10 graines, 10 s. Départ commun
(glouton) : objectif 31 565 (F2 8 265), non faisable.

| Méthode | Solutions proposées (dont grâce à la tolérance) | Objectif F2 + report [IC 95 %] | F2 commun | Patients reportés | Occupation du bloc |
|---|---|---|---|---|---|
| RS seul | 10 / 10 (0) | **7 714** [7 533 ; 7 895] | 3 434 | 22,9 | 92,6 % |
| AGS>RS>TABOU | 10 / 10 (0) | 8 352 [8 148 ; 8 556] | 3 632 | 24,8 | 91,8 % |
| RS>AGS>TABOU | 10 / 10 (3) | 9 450 [9 229 ; 9 672] | 4 030 | 28,1 | 90,7 % |
| memetique | 10 / 10 (1) | 9 574 [9 212 ; 9 937] | 3 974 | 29,1 | 90,5 % |
| TABOU seul | 10 / 10 (2) | 10 765 [10 435 ; 11 095] | 4 055 | 34,4 | 90,3 % |
| AGS seul | 9 / 10 (5) | 22 583 [22 064 ; 23 103] | 6 050 | 70,1 | 84,5 % |

**Tests appariés par graine** (Wilcoxon, Holm ; `donnees_agregees/n2_tests_confirmatoires.csv`) : memetique est moins
bon que RS seul (10 / 10, p = 0,006), meilleur que TABOU seul (10 / 10, p = 0,006) et qu'AGS seul (9 / 9, p = 0,006) ;
AGS>RS>TABOU est moins bon que RS seul (10 / 10, p = 0,002, exploratoire).

**Budget** (objectif, 3 graines ; 2 / 5 / 10 / 20 s) : RS seul 9 212, 8 193, 7 649, 7 443 ; AGS>RS>TABOU 10 831, 8 886,
8 209, 7 889 ; memetique 25 156, 17 783, 9 508, 8 621 ; TABOU seul 19 655, 13 186, 10 903, 9 305 ; AGS seul ne propose
aucune solution à 2 s.

**Rapidité** : TABOU seul est le premier à améliorer le départ (0,04 s en N2 ; RS>AGS>TABOU 0,32 s ; RS seul 3,4 s) et
atteint son meilleur score N1 en 0,14 s, mais il plafonne : à 10 s il n'est que cinquième en N2.

## N1 — instance d'étude fictive (8 chirurgiens, 3 salles, 45 blocs de 2 h)

Toutes les méthodes sont faisables (10 graines, 10 s). Départ : F1 = 1 750.

| Méthode | F1 moyen ± écart-type | Meilleur | Gain vs départ |
|---|---|---|---|
| RS seul | 900 ± 0 | 900 | 48,6 % |
| RS>AGS>TABOU | 900 ± 0 | 900 | 48,6 % |
| AGS>RS>TABOU | 910 ± 21 | 900 | 48,0 % |
| memetique | 950 ± 47 | 900 | 45,7 % |
| TABOU seul | 960 ± 32 | 950 | 45,1 % |
| AGS seul | 1 005 ± 50 | 950 | 42,6 % |

## SMA — 21 scénarios déterministes, mêmes événements

| Stratégie | Urgences dans le délai | Décalés | Reportés | Liste d'attente | Temps réel cumulé |
|---|---|---|---|---|---|
| Contract Net seul (site) | 21 / 23 | 26 | 54 | 8 | 6,0 s |
| + optimisation locale TABOU seul | 21 / 23 | 27 | 54 | 8 | 10,7 s |
| + optimisation globale memetique | 21 / 23 | 50 | 49 | 5 | 65,1 s |
| locale + globale | 21 / 23 | 52 | 47 | 4 | 68,8 s |

Réoptimisation globale seule, 1 s (`donnees_agregees/v3_pilote/sma_reoptimisation_globale.csv`) : score du programme
427 110 sans réoptimisation ; **343 793 avec memetique** (14 plans appliqués sur 57) ; 349 887 avec AGS>RS>TABOU (13 sur
57) ; 427 110 avec RS seul (aucun plan appliqué).

**Sensibilité des coefficients du SMA** (`sma/sma_sensibilite.py`, chaque coefficient × 0,5 puis × 2, 3 439
affectations comparées) : la déprogrammation, le report, le retard et l'attente des urgences différables sont les
coefficients qui changent le plus de décisions (jusqu'à 29 affectations, soit moins de 1 %) ; l'avance, la reprise
par un autre chirurgien et l'attente des urgences urgentes ont un effet faible ; les 6 autres coefficients n'en ont
aucun.

## Limites

Une seule instance réelle (planning v28), patients synthétiques, une graine Mesa pour le SMA, fonction de score en
cours de refonte : ces choix sont à revérifier après la refonte du score.

**Point encore ouvert** : dans la semaine de surcharge aléatoire, 3 graines sur 5 font échouer le SMA
(`KeyError: 'chir_7'`, pour toutes les stratégies) : un chirurgien du service sans vacation sur l'horizon de 2
semaines est proposé comme compétent alors qu'aucun agent n'existe pour lui. Ces exécutions sont marquées ÉCHEC dans
`sma_scenarios.csv` (colonne `echec`). Correction à faire : ne proposer que les chirurgiens qui ont un agent (l'étude
de sensibilité du SMA contourne déjà ce cas).

Commandes pour régénérer ces résultats : section 7 du [README](../README.md).
