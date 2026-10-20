# Branche v3 — corrections du score, de la faisabilité et de l'étude de sensibilité

Base : branche `test` (travail de calibrage) + `v2`. Note : lors du nettoyage du dossier, les fichiers de l'étude de
sensibilité (`sensibilite_poids/`), de `v3_pilote/pilote_v3.csv` et de `donnees_agregees/v2/` ont été retirés ; ils
restent dans l'historique git (commit `d06aad8`) et `python metaheuristiques/sensibilite_poids.py` les régénère. Note : lors du nettoyage du dossier, les fichiers de l'étude de
sensibilité (`sensibilite_poids/`), de `v3_pilote/pilote_v3.csv` et de `donnees_agregees/v2/` ont été retirés ; ils
restent dans l'historique git (commit `d06aad8`) et `python metaheuristiques/sensibilite_poids.py` les régénère. Les campagnes de `v2` (fichiers `n2_*.csv`, `RESUME.md`…) ont été
produites **avant** ces corrections ; elles ne sont pas relancées ici. Les chiffres ci-dessous viennent de pilotes
courts (`donnees_agregees/v3_pilote/`, `sensibilite_poids/`).

## 1. Score et faisabilité — corrigé

| Problème relevé | Correction |
|---|---|
| Aucune méthode ne garde la meilleure solution faisable rencontrée ; le choix final se fait sur le score seul | `ProblemeHybrideN2` retient, pendant la recherche (RS, Tabou, AGS), la meilleure solution **faisable** rencontrée ; c'est elle qui est **proposée** (`solution_finale`). À défaut, la meilleure solution trouvée est rendue et signalée non valide |
| Le validateur n'accepte aucune minute de dépassement | Tolérance `TOLERANCE_DEPASSEMENT_VACATION_MIN` = **10 min** au-delà de la capacité utile (`commun/parametres.py`), commune au validateur et à l'état incrémental (`EtatNiveau2.faisable`) ; F2 pénalise toujours chaque minute |
| Les méthodes sont classées sur F2 commun alors qu'elles optimisent F2 + report | Le meilleur mode hybride est choisi sur le **critère optimisé** (F2 + pénalité de report), après la faisabilité ; F2 commun reste publié |

**Pilote** (cohorte de référence, 3 graines, 10 s, classement sur F2 + report) :

| Méthode | Solutions proposées | Objectif F2 + report | F2 commun | Patients reportés | Occupation bloc |
|---|---|---|---|---|---|
| RS seul | 3 / 3 | 7 535 | 3 468 | 22,0 | 92,7 % |
| AGS>RS>TABOU | 3 / 3 | 8 162 | 3 562 | 25,0 | 92,0 % |
| RS>AGS>TABOU | 3 / 3 | 8 708 | 3 774 | 27,0 | 91,3 % |
| memetique | 3 / 3 | 9 098 | 3 932 | 27,7 | 91,1 % |
| TABOU seul | 3 / 3 | 10 450 | 3 983 | 33,3 | 90,5 % |
| AGS seul | 3 / 3 | 22 118 | 5 852 | 69,7 | 84,7 % |

Toutes les méthodes proposent maintenant une solution faisable (contre 70 à 90 % des exécutions en v2). Chiffres du
fichier actuel `pilote_v3.csv` (le pilote a été relancé ; la première exécution donnait le même classement). Le classement
ne change pas : RS seul reste en tête. Ce n'est pas un effet du critère de comparaison : RS seul est meilleur sur F2
**et** sur la pénalité de report.

## 2. Mode mémétique : polissage des enfants par un RS court — pilote, NON intégré

Pilote (`donnees_agregees/v3_pilote/pilote_memetique_rs*.csv`) : cohorte de référence, 5 graines, 10 s et 30 s,
option `ParametresRechercheLocale(polissage_enfant="rs", iterations_rs_enfant=300 | 1500)` (défaut inchangé : Tabou).
Objectif = F2 + report de la solution proposée (moyenne de 5 graines, à minimiser).

| Budget | RS seul | AGS>RS>TABOU | memetique actuel | memetique RS 300 | memetique RS 1500 |
|---|---|---|---|---|---|
| 10 s | **7 497** | 8 424 (173 gén.) | 8 799 (8 gén.) | 8 889 (144 gén.) | 8 774 (87 gén.) |
| 30 s | **7 080** | 7 738 (531 gén.) | 7 997 (23 gén.) | 7 960 (497 gén.) | 8 032 (285 gén.) |

Le polissage par RS fait réellement tourner l'AGS (centaines de générations), mais il **n'améliore pas nettement le
mémétique** (2 ou 3 graines gagnées sur 5 selon la variante et le budget, non significatif), il **perd contre RS seul
sur les 5 graines aux deux budgets** (écart médian +980 à +1 450 ; Wilcoxon apparié p = 0,062, le minimum possible
avec 5 paires) et contre AGS>RS>TABOU (0 à 2 graines gagnées sur 5). **Décision (règle de
l'équipe)** : le mémétique reste tel quel ; **AGS>RS>TABOU est présenté comme l'hybridation de référence**. L'option
reste dans le code, désactivée, pour reproduire le pilote.

### Tolérance de dépassement (point 2)

Remplacée par **min(5 min, 25 % de la marge de la vacation)** au-delà de la capacité utile
(`Vacation.tolerance_depassement_minutes`, paramètres `TOLERANCE_DEPASSEMENT_MAX_MIN` et `PART_MARGE_TOLEREE`) :
5 min pour une vacation de 5 h (marge 30 min), 3 min pour 2 h. Le validateur a un mode strict
(`valider_niveau2(..., avec_tolerance=False)`) ; la campagne publie, par méthode, le nombre de solutions faisables
**seulement grâce à la tolérance** (`proposees_grace_tolerance`).

### SMA (point 4)

**solution_finale côté SMA : nécessaire, corrigé.** L'agent Optimisation rejette tout le plan si la solution finale
n'est pas applicable (hors des heures du programme, valeur interdite, lit / place au-delà du plafond), même si une
solution applicable a été rencontrée. Les états du SMA ont maintenant `faisable()` (même règle que l'application du
plan), le coût du moteur retient la meilleure solution applicable, et `metaheuristiques_sma.optimiser` appelle
`solution_finale`. Sur les 21 scénarios, aucun plan n'a été rejeté pour non-faisabilité (la protection n'a pas eu à
jouer) ; les 15 scénarios du projet restent cohérents.

**Réoptimisation globale (21 scénarios, budget 1 s, sans optimisation locale)** —
`donnees_agregees/v3_pilote/sma_reoptimisation_globale.csv` :

| Méthode | Plans appliqués / calculés | Gain cumulé | Score du programme | Décalés | Reportés | Liste d'attente | Urgences dans le délai |
|---|---|---|---|---|---|---|---|
| aucune (site) | — | — | 427 110 | 26 | 54 | 8 | 21 / 23 |
| memetique | 14 / 57 | 93 054 | **343 793** | 48 | 48 | 5 | 21 / 23 |
| AGS>RS>TABOU | 13 / 57 | 95 245 | 354 437 | 52 | 45 | 6 | 21 / 23 |
| RS seul | 0 / 58 | 0 | 427 110 | 26 | 54 | 8 | 21 / 23 |

**Recommandation : garder memetique** pour la réoptimisation globale (meilleur score, moins de patients décalés que
AGS>RS>TABOU ; écart de 3 % sur le score du programme). Une première exécution donnait 345 093 contre 347 560
(0,7 %) : avec un budget en temps réel, l'écart varie d'une exécution à l'autre, mais memetique est devant les deux
fois. **RS seul est à exclure** : en 1 s
il n'améliore jamais le programme (température encore trop haute, aucun plan ne dépasse le gain minimal de 50).
Une seule graine Mesa : la différence memetique / AGS>RS>TABOU n'est pas significative.

## 3. Étude de sensibilité des poids — réécrite

Les fichiers de calibrage de la branche `test` (`commun/calibrer_coefficients.py`, `commun/calcul_coeff`) utilisaient
une **ancienne copie** de l'hybridation (`commun/hybridage2.py`, antérieure aux corrections du nettoyage : reports
dupliqués, échanges avant la date au plus tôt). Ils sont remplacés par `metaheuristiques/sensibilite_poids.py` ;
l'étude SMA (`commun/calcul_poids_sma`) est rangée dans `sma/sma_sensibilite.py`, inchangée.

| Problème relevé | Correction |
|---|---|
| Poids testés un par un | Tirage **conjoint** log-uniforme (×0,1 à ×10 sur chaque poids), plus le jeu actuel |
| Critère de 60 min de dépassement, différent du validateur | Viable = solution proposée **faisable pour le validateur** (tolérance de 10 min) |
| Jeu actuel jugé non viable (« 12 prioritaires reportés ») | Plus de comparaison au meilleur absolu ; dominance au sens de **Pareto** : au moins aussi bon sur les reportés **et** l'occupation, strictement meilleur sur l'un, sans plus de prioritaires reportés |
| Plages réduites à la plus petite valeur testée | Pas de valeur « recommandée » au bord : plages des jeux non dominés, signalées ouvertes si elles touchent le bord |
| Instance v28 de référence différente (45 reportés, 78 %) | **Cohorte de référence des campagnes** (100 %) + charge 85 %, capacités du site 30 / 3 / 20 |
| Lit en trop recommandé à 158 114 | Lits et places = contraintes dures du validateur ; coût fixé à **5 000** (échelle commune avec le SMA) ; l'étude vérifie seulement qu'aucune solution ne déborde |

**Résultat** (60 jeux tirés + l'actuel, 2 instances, 3 graines, RS 5 s, 8 min ; `sensibilite_poids/`) :
- 46 jeux sur 61 sont **viables** (validateur) ; le **jeu actuel l'est** ; avec lit = place = 5 000, **aucune**
  solution proposée ne déborde en lits ou en places (l'échelle commune avec le SMA tient) ;
- les 15 jeux non viables ont presque tous un poids de **dépassement** ≤ ×0,22 ou un poids **non placé** ≤ ×0,33 :
  ce sont les deux poids qui ne doivent pas baisser ;
- au sens de Pareto strict, le jeu actuel (12,8 reportés, 0 prioritaire, 88,0 %) est dominé par 5 jeux, mais de très
  peu (au plus 1,2 reporté et 0,7 point d'occupation en moins), **en dessous de la variabilité entre graines du jeu
  actuel lui-même** (23 à 26 reportés et 91,6 à 92,7 % sur l'instance de référence) : ces dominations ne sont pas
  significatives ;
- les 5 jeux non dominés contiennent tous le facteur 1 dans leur plage, pour chacun des 6 poids : **les poids actuels
  sont dans la zone des meilleurs compromis** ; les plages touchent le bord testé vers le haut pour non placé, des
  deux côtés pour dépassement (un poids de dépassement très bas n'est donc pas toujours non viable, mais il l'est
  souvent) et vers le bas pour var_lits : aucune valeur « optimale » n'en est déduite.

## 4. Campagne N2 finale relancée sur v3

Voir `RESUME.md` (comparaison avec v2).
