# Branche v3 — corrections du score, de la faisabilité et de l'étude de sensibilité

Base : branche `test` (travail de calibrage) + `v2`. Les campagnes de `v2` (fichiers `n2_*.csv`, `RESUME.md`…) ont été
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
| RS seul | 3 / 3 | 7 764 | 3 397 | 23,7 | 92,7 % |
| AGS>RS>TABOU | 3 / 3 | 8 140 | 3 506 | 25,0 | 92,1 % |
| RS>AGS>TABOU | 3 / 3 | 8 749 | 3 649 | 26,0 | 91,7 % |
| memetique | 3 / 3 | 8 833 | 3 899 | 26,7 | 91,1 % |
| TABOU seul | 3 / 3 | 10 450 | 3 983 | 33,3 | 90,5 % |
| AGS seul | 3 / 3 | 19 674 | 5 641 | 64,3 | 85,5 % |

Toutes les méthodes proposent maintenant une solution faisable (contre 70 à 90 % des exécutions en v2). Le classement
ne change pas : RS seul reste en tête. Ce n'est pas un effet du critère de comparaison : RS seul est meilleur sur F2
**et** sur la pénalité de report.

## 2. Le mode mémétique ne « fait » presque pas d'algorithme génétique — à valider

Constat : en 10 s, memetique ne fait que **8 générations** (15 en 20 s ; RS>AGS>TABOU : 5). Chaque enfant est poli
par 15 itérations de Tabou, d'environ 380 voisins chacune : le polissage consomme presque tout le budget.

| Piste testée | Générations en 10 s | Objectif F2 + report | Conclusion |
|---|---|---|---|
| memetique actuel (polissage 15 itérations) | 8 | 8 833 | — |
| polissage 3 itérations | 34 | 8 983 | plus de génétique, pas mieux |
| polissage 1 itération | 76 | 9 013 | plus de génétique, pas mieux |
| budget 20 s (campagne v2) | 15 | F2 3 610 (RS seul 20 s : 3 247) | doubler le budget ne suffit pas à dépasser RS seul |

Augmenter le budget n'est donc **pas** une solution : il faudrait des budgets inégaux (comparaison faussée) et, même
à 20 s, memetique reste derrière RS seul. Alléger le polissage fait tourner la génétique sans améliorer le résultat :
sur cette instance, le croisement (par chirurgien) apporte peu face à la recherche locale.

**Propositions (non appliquées, à valider)** :
1. **Polir les enfants par un RS court au lieu du Tabou** : le RS est la recherche locale la plus efficace ici et
   coûte une évaluation par mouvement (contre ~380 pour une itération de Tabou) ; l'AGS ferait des centaines de
   générations, chacune améliorée par la meilleure recherche locale. Changement localisé
   (`RechercheLocaleMixte`, phase « enfant »), à évaluer par un pilote de quelques minutes.
2. **Assumer le résultat** : présenter memetique tel quel, en expliquant que la composante génétique n'apporte pas
   de gain sur cette instance et à ce budget (résultat négatif publiable), et retenir RS seul ou AGS>RS>TABOU pour
   le site.
3. Garder AGS>RS>TABOU comme hybridation de référence : c'est la seule qui fait réellement tourner l'AGS (≈ 240
   générations) et elle arrive deuxième, proche de RS seul.

## 3. Étude de sensibilité des poids — réécrite

Les fichiers de calibrage de la branche `test` (`commun/calibrer_coefficients.py`, `commun/calcul_coeff`) utilisaient
une **ancienne copie** de l'hybridation (`commun/hybridage2.py`, antérieure aux corrections du nettoyage : reports
dupliqués, échanges avant la date au plus tôt). Ils sont remplacés par `metaheuristiques/sensibilite_poids.py` ;
l'étude SMA (`commun/calcul_poids_sma`) est rangée dans `sma/sma_sensibilite.py`, inchangée.

| Problème relevé | Correction |
|---|---|
| Poids testés un par un | Tirage **conjoint** log-uniforme (×0,1 à ×10 sur chaque poids), plus le jeu actuel |
| Critère de 60 min de dépassement, différent du validateur | Viable = solution proposée **faisable pour le validateur** (tolérance de 10 min) |
| Jeu actuel jugé non viable (« 12 prioritaires reportés ») | Plus de comparaison au meilleur absolu ; le jeu actuel est jugé par **dominance nette** (≥ 2 reportés en moins **et** ≥ 3 points d'occupation en plus, sans plus de prioritaires reportés) |
| Plages réduites à la plus petite valeur testée | Pas de valeur « recommandée » au bord : plages des jeux non dominés, signalées ouvertes si elles touchent le bord |
| Instance v28 de référence différente (45 reportés, 78 %) | **Cohorte de référence des campagnes** (100 %) + charge 85 %, capacités du site 30 / 3 / 20 |
| Lit en trop recommandé à 158 114 | Lits et places = contraintes dures du validateur ; coût fixé à **5 000** (échelle commune avec le SMA) ; l'étude vérifie seulement qu'aucune solution ne déborde |

**Résultat** (31 jeux, 2 instances, 2 graines, RS 5 s, 3 min) : le **jeu actuel est viable** et **n'est nettement
dominé par aucun autre** (12 reportés, 0 prioritaire, 88,1 % ; meilleurs jeux non dominés : 11,5 reportés, 88,8 %).
Avec lit = place = 5 000, **aucune** solution proposée ne déborde. Les jeux non viables ont un poids de dépassement
trop faible (×0,11 à ×0,17) ou un poids « non placé » trop faible (×0,17 à ×0,25). Seuls 3 jeux sont non dominés : les
plages par poids restent indicatives (`--tirages 60 --graines 3` pour les affiner, ≈ 10 min).

Fichiers : `sensibilite_poids/essais.csv`, `jeux.csv`, `sensibilite.json`, `compromis.png`, `plages.png`.

## 4. À relancer après validation

Les campagnes N2 complètes (`scripts/de_optimisation.py final`, ≈ 20 min) puis `e_analyse.py`, `f_ressources.py`,
`g_saturation_robustesse.py robustesse`, `j_tableaux.py`, pour que `RESUME.md` et les tableaux reflètent la
tolérance, la solution proposée et le nouveau critère de classement.
