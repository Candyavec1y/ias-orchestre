# OR'CHESTRE — Résumé des résultats (campagnes P0 et P1)

Branche v3 (campagne N2 relancée ; ML, N1, SMA et saturation : commit `d8fbf35`), Apple M2, budget de 10 s par exécution de métaheuristique. Toutes les valeurs proviennent des
fichiers mesurés de ce dossier (voir `manifest.json`). Statuts : MESURÉ sauf indication contraire. Les anciennes
valeurs des soutenances ne sont pas reprises.

## 1. Machine learning (4 modèles ; urgence = règle)

Jeu de test de 2 896 séjours (séparation 80 / 20 **par séjour**, 35,5 % des séjours de test avec un patient vu à
l'entraînement). *Résultats provisoires : l'équipe va revoir le ML.*

| Modèle | Performance | Référence simple |
|---|---|---|
| Durée au bloc | R² 0,670 ; MAE 14,8 min ; P90 de l'erreur 32,4 min | médiane par type d'intervention : R² 0,45 ; MAE 19,1 min |
| Mode ambulatoire / hospitalisé | accuracy 0,925 ; F1 0,933 / 0,915 ; Brier 0,056 | classe majoritaire : 0,550 |
| Nuits après (hospitalisés, n = 1 304) | R² 0,695 ; MAE 0,54 ; ≤ 1 nuit : 85,1 % | médiane : MAE 1,13 ; 77,9 % |
| Nuits avant (hospitalisés) | R² 0,03 ; MAE 0,26 | médiane (0 nuit) : MAE 0,29 — **pas d'apport net** |

Les interventions de plus de 2 h sont sous-estimées dans 80,5 % des cas (−26,7 min en moyenne). Le score d'urgence
est une règle CIM-10 / CCAM, non validée cliniquement, sans métrique ML.

## 2. Niveau 1 (instance d'étude fictive : 8 chirurgiens, 3 salles, 45 blocs de 2 h)

Toutes les méthodes produisent des plannings **faisables** (10 graines). Départ commun : F1 = 1 750.

| Méthode | F1 moyen ± écart-type | Meilleur | Gain vs départ (moyen) |
|---|---|---|---|
| RS seul | 900 ± 0 | 900 | 48,6 % |
| RS>AGS>TABOU | 900 ± 0 | 900 | 48,6 % |
| AGS>RS>TABOU | 925 ± 35 | 900 | 47,1 % |
| memetique | 940 ± 62 | 900 | 46,3 % |
| TABOU seul | 960 ± 32 | 950 | 45,1 % |
| AGS seul | 1 005 ± 50 | 950 | 42,6 % |

La meilleure valeur observée (900) n'est pas une borne prouvée : aucun gap d'optimalité n'est calculé.

## 3. Niveau 2 sur le planning réel v28 (4 semaines + 3 semaines de report) — branche v3

**Règles (v3)** : pendant la recherche, un dépassement de capacité n'est que pénalisé ; chaque méthode **propose la
meilleure solution faisable rencontrée** ; une vacation peut dépasser sa capacité utile d'au plus **min(5 min, 25 %
de sa marge)** ; les méthodes sont **classées sur le critère qu'elles optimisent**, l'objectif F2 + pénalité de report
(F2 commun publié à côté). *Résultats provisoires : l'équipe refait la fonction de score.*

**Cohorte de référence** (421 patients, charge 99 % de la capacité utile, 10 graines, 10 s). Départ commun (glouton +
placement des restants) : objectif 31 565 (F2 8 265), non faisable ; référence, non proposé.

| Méthode (classée sur l'objectif) | Solutions proposées (dont grâce à la tolérance) | Objectif F2 + report [IC 95 %] | F2 commun | Report | Patients reportés | Occupation bloc |
|---|---|---|---|---|---|---|
| RS seul | 10 / 10 (0) | **7 702** [7 488 ; 7 915] | 3 422 | 4 280 | 23,3 | 92,6 % |
| AGS>RS>TABOU (hybridation de référence) | 10 / 10 (1) | 8 241 [8 092 ; 8 389] | 3 601 | 4 640 | 24,9 | 91,9 % |
| RS>AGS>TABOU | 10 / 10 (1) | 9 153 [8 833 ; 9 473] | 3 893 | 5 260 | 27,5 | 91,0 % |
| memetique | 10 / 10 (0) | 9 584 [9 157 ; 10 010] | 4 014 | 5 570 | 29,1 | 90,5 % |
| TABOU seul | 10 / 10 (2) | 10 580 [10 325 ; 10 834] | 4 000 | 6 580 | 33,9 | 90,5 % |
| premier créneau (adaptateur) | 1 / 1 (0) | 13 784 | 5 484 | 8 300 | 36 | 88,0 % |
| AGS seul | 9 / 10 (5) | 22 331 [21 792 ; 22 870] | 6 020 | 16 311 | 70,0 | 84,6 % |

**Tests appariés par graine** (Wilcoxon, Holm sur la famille fixée a priori) :
- sur l'**objectif** : memetique est **moins bon que RS seul** (10 / 10 ; p corrigé = 0,006), **meilleur que TABOU
  seul** (9 / 10 ; p = 0,008) et qu'AGS seul (9 / 9 ; p = 0,008) ; exploratoire : AGS>RS>TABOU est moins bon que RS
  seul (10 / 10 ; p = 0,002) ;
- sur **F2 commun** : mêmes conclusions, sauf memetique contre TABOU seul, non différents (p = 1).
La pénalité de report départage donc memetique et TABOU seul : à F2 égal, memetique reporte moins de patients.

**Charge** (3 cohortes × 3 graines) : à 70 %, toutes les méthodes proposent une solution à chaque exécution (écart
≤ 3 % à la meilleure pour les métaheuristiques, sauf AGS seul : 20 %) ; à **85 %, 9 exécutions sur 9** pour toutes les métaheuristiques (dont 3 ou
4 grâce à la tolérance) ; à 100 %, 3 sur 9 (seule la cohorte de référence a une solution faisable : les cohortes 44 et
45 gardent 1 ou 2 vacations au-delà de la tolérance) ; à 115 %, **aucune**.

**Budget** (2 / 5 / 10 / 20 s, 3 graines, objectif) : RS seul est le meilleur à tous les budgets (9 157 à 2 s ; 7 251 à
20 s), AGS>RS>TABOU deuxième (10 909 à 2 s ; 7 722 à 20 s) ; à 2 s, AGS seul ne propose aucune solution.

### Comparaison avec v2

| | v2 | v3 |
|---|---|---|
| Exécutions avec une solution proposée (référence) | 7 à 10 sur 10 selon la méthode | 9 ou 10 sur 10 (AGS seul 9) |
| À 85 % de charge | 5 ou 6 sur 9 | 9 sur 9 |
| Solutions faisables seulement grâce à la tolérance (référence) | — | 9 sur 59 solutions proposées par les métaheuristiques (dont AGS seul : 5) |
| Classement | F2 commun : RS seul, AGS>RS>TABOU, memetique, RS>AGS>TABOU, TABOU seul, AGS seul | objectif : RS seul, AGS>RS>TABOU, RS>AGS>TABOU, memetique, TABOU seul, AGS seul |
| RS seul (F2 commun) | 3 344 | 3 422 |
| memetique (F2 commun) | 3 823 | 4 014 |

v3 est **plus cohérent** : chaque méthode propose une solution valide, et le classement porte sur ce qu'elles
optimisent. Il **n'est pas meilleur en score** : la solution proposée est parfois une solution faisable un peu moins
bonne que la meilleure solution non faisable que v2 rendait, d'où un F2 commun légèrement plus élevé (+2 à +5 %). La
hiérarchie ne change pas en tête : RS seul, puis AGS>RS>TABOU.

## 4. Coordination bloc / lits / places (cohorte de référence, solutions proposées)

Les méthodes qui remplissent le plus le bloc (RS seul : 92,6 %) ont le pic de lits le plus haut (25,6) ; AGS seul
remplit le moins (84,6 %) avec le pic le plus bas (23,2). Aucun lit n'est utilisé au-delà des 27 lits programmables ;
les places ambulatoires ne sont jamais saturées. Délai moyen entre la date au plus tôt et l'intervention : 3,6 jours
(RS seul, AGS>RS>TABOU) à 6,0 jours (AGS seul) ; 6,7 jours pour le départ glouton.

## 5. Saturation et robustesse

- **Saturation** (programme vide, patients au profil réel, SMA ; inchangée en v3) : 432 patients opérés en 4 semaines
  (426 à 437 selon la graine) ; 95,1 % de la capacité utile ; la ressource limitante est le **temps opératoire**.
- **Robustesse des solutions proposées** (réévaluées sans réoptimisation) : avec des durées +10 %, aucune minute au-delà
  de la durée totale des vacations, mais plus aucun programme faisable au sens de la capacité utile ; **+20 %** : 79 à
  93 vacations en heures supplémentaires, de 1 040 min (memetique) à 1 233 min (RS seul) ; **bruit lognormal
  σ = 0,25** : 421 (memetique) à 489 min (RS seul) en moyenne ; **6 lits de moins** : tous les programmes deviennent non
  faisables (2,4 à 6,3 nuits en dépassement en moyenne). Les programmes les plus remplis sont les plus exposés.

## 6. Système multi-agent

21 scénarios déterministes et 2 scénarios aléatoires (5 graines), 4 stratégies à événements identiques :
- 21 des 23 urgences dans le délai pour toutes les stratégies ; 1 transfert **proposé** (spécialité non couverte),
  1 urgence hors délai confiée à la garde ; 0 incohérence ;
- l'optimisation globale réduit la liste d'attente (8 → 4) au prix de 2 fois plus de patients décalés et d'un temps
  de calcul 11 fois plus long ; l'optimisation locale seule ne change presque rien ;
- **3 des 5 graines de la semaine en surcharge font échouer le moteur** (KeyError `chir_7`), pour toutes les
  stratégies ;
- temps réel de régulation d'une urgence : 4 ms (configuration du site) ; 1,2 s avec les optimisations.

Le programme figé et la régulation simple ne sont pas disponibles : l'apport du SMA par rapport à une absence de
régulation n'est pas mesuré.

**Réoptimisation globale (v3, 21 scénarios, 1 s)** : memetique et AGS>RS>TABOU sont équivalents (score du programme
345 093 contre 347 560, 14 et 13 plans appliqués sur 57) ; RS seul n'applique aucun plan en 1 s. **memetique est
conservé** pour la réoptimisation globale. Côté SMA aussi, la solution proposée est maintenant la meilleure solution
applicable rencontrée.

## 7. Sensibilité des poids (v3)

60 jeux de poids tirés ensemble (×0,1 à ×10), 2 instances, 3 graines : le jeu actuel est viable ; il n'est dominé au
sens de Pareto que par des écarts inférieurs à sa propre variabilité entre graines, et il est dans la plage de tous
les jeux non dominés pour les 6 poids. Les poids de dépassement et de « non placé » ne doivent pas baisser. Avec
lit = place = 5 000 (échelle commune avec le SMA), aucune solution ne déborde. Détail : `V3_CORRECTIONS.md`.
