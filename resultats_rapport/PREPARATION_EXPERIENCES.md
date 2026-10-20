# Préparation des expériences (contrôle rapide, pas un nouvel audit)

Rédigé **avant** l'analyse des résultats de la campagne finale ; seul le pilote (`pilote_*.csv`, 1 graine, 2 s) avait
été exécuté.

## Code figé

- Commit `d8fbf35abd6e8db531420b6bcaf9b3704957e95a`, branche `nettoyage`, arbre propre hors `resultats_rapport/`.
- Aucun fichier du dépôt n'est modifié par les campagnes : les scripts de `resultats_rapport/scripts/` importent
  les modules du projet (comme l'interface). Les adaptateurs isolés (« premier créneau compatible », mesure du
  temps par événement du SMA) sont dans ces scripts.

## Points d'entrée vérifiés (`donnees_agregees/preparation_controles.md`)

| Contrôle | Résultat |
|---|---|
| `sma/scenarios_sma.py --liste` et `insertion_simple` | code retour 0 |
| `metaheuristiques/hybridation.py --help` | code retour 0 |
| `pytest interface/tests -m "not lent"` | 139 réussis |
| Validateur indépendant (`commun/validation.py`) | appelé dans chaque résultat (`r.validation`) |
| Deux scores N2 | `score_final` = F2 commun ; `score_recherche` = F2 + pénalité de report ; les deux sont exportés |
| Méthodes N1 / N2 | `MODES` = memetique, AGS>RS>TABOU, RS>AGS>TABOU ; `REFERENCES` = AGS seul, RS seul, TABOU seul |
| Stratégies SMA | `ParametresSMA(methode_locale, optimisation_globale)` : 4 combinaisons disponibles |
| Données ML | lecture locale du CSV du projet ; seuls des agrégats sont exportés |

## Défauts ou particularités découverts (sans correction, voir `QUESTIONS.md`)

1. **Départ N2 non faisable** (pilote) : le glouton commun suivi de `placer_restants` laisse un dépassement de
   capacité utile sur une vacation. Le score F2 traite ce dépassement comme une pénalité (100 par minute), le
   validateur comme une violation. Conséquence : une méthode peut rendre un meilleur score sans être faisable. Les
   résultats publient donc séparément le score et la faisabilité, et les écarts à la meilleure solution sont
   calculés **parmi les solutions faisables**.
2. **Dépassement du budget** : le mode RS>AGS>TABOU dépasse le budget de temps (2,9 s pour 2 s dans le pilote). Le
   temps réel de chaque exécution est publié.
3. **Séparation ML par séjour** : 35,5 % des séjours du test ont un patient vu à l'entraînement (`ml_resume.md`).

## Coût estimé et plan

| Bloc | Exécutions | Budget cumulé | Durée estimée |
|---|---|---|---|
| N1 : 10 graines × 6 méthodes + glouton | 70 | 600 s | intégré à la campagne N2 |
| N2 référence (charge 100 %, cohorte 43) : 10 graines × 6 méthodes + glouton + premier créneau | 62 | 600 s | |
| N2 charges 70 / 85 / 100 / 115 %, cohortes 43 / 44 / 45, 3 graines | 220 | 1 980 s | |
| N2 budgets 2 / 5 / 20 s, 3 graines | 54 | 486 s | |
| **Total optimisation** | **406** | **3 666 s** | **≈ 20-30 min sur 4 processus** |
| SMA : 22 scénarios déterministes × 4 stratégies + 2 aléatoires × 5 graines × 4 | 128 | — | ≈ 10-20 min |
| Saturation : étude du projet, 4 semaines, capacités du site / lits illimités / places illimitées | 3 | — | ≈ 10 min |

Exécutions parallèles : 4 processus (M2 : 4 cœurs performance + 4 efficacité). L'ordre des tâches est mélangé
(graine 2026) pour que le passage éventuel sur un cœur d'efficacité ne favorise aucune méthode ; le nombre
d'évaluations est publié.

## Analyses statistiques fixées a priori

- **Comparaison principale (N2, cohorte de référence, 10 graines appariées)** : le mode d'hybridation par défaut
  du projet (`memetique`, choisi avant les résultats) contre chacune des trois méthodes seules (RS, Tabou, AGS) :
  test des rangs signés de Wilcoxon apparié par graine sur le score F2 commun, correction de Holm sur les 3 tests,
  seuil 5 %. La faisabilité est comparée à part (taux de solutions faisables).
- **Hybridations entre elles, charges, budgets, N1** : analyses **exploratoires** (moyenne ± écart-type, médiane,
  IC 95 % de la moyenne, taux de faisabilité), sans test confirmatoire.
- Gain par rapport au départ : `100 × (départ − final) / départ` ; écart à la meilleure solution observée : par
  rapport à la meilleure solution **faisable** de la même instance. Aucun gap d'optimalité (aucune borne valide).
- Une différence non significative n'est pas interprétée comme une équivalence.

## Amendement après les résultats (décision de l'équipe, 20/10/2026)

L'équipe a précisé que seules les solutions faisables sont proposées à la fin d'une recherche (contrainte dure),
les dépassements n'étant tolérés que pendant la recherche. L'analyse a donc été modifiée **après** l'obtention des
résultats : une exécution sans solution finale faisable compte comme « aucune solution proposée », et le test
confirmatoire porte sur les graines où les deux méthodes comparées proposent une solution (10, 9 et 7 paires au lieu
de 10). Les conclusions du test sont inchangées (memetique moins bon que RS seul, meilleur qu'AGS seul, non
distinguable de TABOU seul). Les données brutes (`n2_resultats.csv`) contiennent toutes les exécutions.

## Second amendement (branche v3, 20/10/2026)

Sur demande de l'équipe : tolérance de dépassement min(5 min, 25 % de la marge), solution proposée = meilleure
solution faisable rencontrée (dans le code des métaheuristiques), et classement sur le **critère optimisé** (objectif
F2 + pénalité de report) au lieu de F2 commun. La famille confirmatoire (memetique contre chaque méthode seule, Holm)
est testée sur l'objectif puis, pour comparaison, sur F2 commun ; AGS>RS>TABOU contre RS seul est ajouté à titre
exploratoire (hybridation de référence choisie après le pilote du mémétique). La campagne N2 a été relancée en entier.
