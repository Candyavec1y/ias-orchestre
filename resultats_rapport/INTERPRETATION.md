# Interprétation scientifique

Chaque résultat est présenté avec son protocole, sa mesure, sa référence, son gain et sa contrepartie, sa
faisabilité, ses limites, puis une conclusion prudente. Les chiffres viennent de `RESUME.md` et des CSV.

## 1. Machine learning

*Résultats provisoires : l'équipe va revoir le ML (notamment la séparation par patient).*

1. *Protocole* : 4 modèles HistGradientBoosting réentraînés en mémoire sur 80 % des 14 477 séjours ; test sur 2 896
   séjours (1 304 hospitalisés pour les nuits).
2. *Mesure* : durée au bloc R² 0,670 / MAE 14,8 min ; mode de prise en charge accuracy 0,925 ; nuits après MAE 0,54.
3. *Référence* : médiane par type d'intervention (MAE 19,1 min), classe majoritaire (0,550), médiane des nuits
   (MAE 1,13).
4. *Gain / contrepartie* : un gain net sur la durée, le mode et les nuits après ; **aucun gain sur les nuits avant**.
   La durée des longues interventions est systématiquement sous-estimée (−26,7 min au-delà de 2 h), ce qui pèse sur
   la marge des vacations.
5. *Faisabilité* : sans objet.
6. *Limites* : séparation par séjour avec 35,5 % de recouvrement de patients (risque de fuite) ; une seule
   séparation, sans intervalle de confiance ; les cohortes N2 ne viennent pas du ML.
7. *Conclusion* : les modèles de durée et de mode sont utiles comme **propositions** au chirurgien ; le modèle des
   nuits avant peut être remplacé par la médiane. Une réévaluation par patient est nécessaire avant toute
   affirmation de généralisation.

## 2. Niveau 1 (instance d'étude fictive uniquement)

1. *Protocole* : 6 méthodes × 10 graines, 10 s, départ commun (F1 = 1 750).
2. *Mesure* : toutes faisables ; RS seul et RS>AGS>TABOU atteignent 900 à chaque graine ; AGS seul 1 005 ± 50.
3. *Référence* : solution de départ.
4. *Gain* : 42,6 à 48,6 % ; *contrepartie* : aucune contrainte violée ; les écarts restants portent sur la
   fragmentation et les changements de salle.
5. *Faisabilité* : 100 % (validateur indépendant).
6. *Limites* : petite instance fictive, aucune borne inférieure (pas de gap d'optimalité) ; le N1 n'est pas appliqué
   au planning réel v28 et aucun chaînage N1 → N2 sur v28 n'est démontré.
7. *Conclusion* : sur cette instance, la recherche locale (RS) suffit ; les hybridations n'apportent pas de gain
   au-delà de la meilleure valeur observée.

## 3. Niveau 2 et coordination des ressources (branche v3)

*Résultats provisoires : l'équipe refait la fonction de score.*

1. *Protocole* : planning v28, 4 semaines + 3 semaines de report, cohorte synthétique de référence de 421 patients
   (99 % de la capacité utile), 10 graines appariées, 10 s ; charges 70 à 115 %, budgets 2 à 20 s. Chaque méthode
   propose la meilleure solution faisable rencontrée (tolérance min(5 min, 25 % de la marge)) ; classement sur
   l'objectif optimisé (F2 + report).
2. *Mesure* : RS seul 7 702 [IC 95 % : 7 488 ; 7 915], AGS>RS>TABOU 8 241, RS>AGS>TABOU 9 153, memetique 9 584, TABOU
   seul 10 580, AGS seul 22 331 ; toutes proposent une solution à chaque exécution (AGS seul : 9 sur 10).
3. *Référence* : départ commun (objectif 31 565, non faisable) et premier créneau compatible (13 784).
4. *Gain / contrepartie* : 66 à 76 % de gain sur l'objectif pour les métaheuristiques autres qu'AGS seul ; les
   meilleures solutions remplissent davantage le bloc et reportent moins, **en échange** d'un pic de lits plus haut
   et d'une plus forte exposition aux allongements de durée (jusqu'à 1 233 minutes d'heures supplémentaires à +20 %).
5. *Faisabilité* : 9 solutions proposées sur 59 ne sont faisables que grâce à la tolérance (5 pour AGS seul) ; à 85 %
   de charge toutes les exécutions proposent une solution (contre 5 ou 6 sur 9 en v2) ; à 115 %, aucune.
6. *Limites* : cohortes synthétiques, un seul planning, nombre d'évaluations non comparable entre méthodes, score en
   cours de refonte.
7. *Conclusion* : **les hybridations ne sont pas préférables à RS seul sur cette instance et à ce budget**, quel que
   soit le critère (objectif ou F2). L'hybridation de référence est **AGS>RS>TABOU** (deuxième, seule hybridation qui
   fait tourner l'AGS) ; polir les enfants du mémétique par un RS court ne le rend pas compétitif (pilote, 0 graine
   gagnée sur 5 contre RS seul). Sur l'objectif, memetique est meilleur que TABOU seul (ils sont à égalité sur F2) :
   la pénalité de report les départage.

## 4. Système multi-agent

1. *Protocole* : 21 scénarios déterministes + 2 scénarios aléatoires × 5 graines ; 4 stratégies disponibles,
   mêmes événements ; programme figé et régulation simple NON DISPONIBLES.
2. *Mesure* : 21 / 23 urgences dans le délai pour toutes les stratégies ; 0 incohérence ; 97,3 % du planning
   conservé en moyenne (configuration du site).
3. *Référence* : la configuration du site (Contract Net sans métaheuristique) ; **aucune référence sans régulation**.
4. *Gain / contrepartie* : l'optimisation globale vide la liste d'attente (8 → 4) mais double les patients décalés
   et multiplie le temps de calcul par 11 ; l'optimisation locale n'a presque pas d'effet.
5. *Faisabilité* : 1 transfert proposé, soumis à décision humaine (spécialité non couverte) ; 1 urgence hors délai
   (journée surchargée avec panne) ; **3 graines sur 5 de la semaine en surcharge font échouer le moteur**.
6. *Limites* : un seul programme initial, une seule graine Mesa, scénarios choisis à la main ; les transferts sont
   proposés, jamais réalisés.
7. *Conclusion* : la régulation de base répond aux urgences dans le délai sur les cas testés, de manière cohérente ;
   l'ajout des optimisations est un arbitrage (moins d'attente contre plus de déplacements), pas un gain net ; la
   robustesse en surcharge n'est pas acquise tant que le défaut `chir_7` n'est pas corrigé.

## 5. Robustesse

- *Algorithmique* (graines) : écarts-types de 208 à 596 sur l'objectif des solutions proposées (2,5 à 6,2 % de la
  moyenne, hors AGS seul) ; RS seul et RS>AGS>TABOU
  atteignent la même valeur N1 à chaque graine.
- *Opérationnelle* (perturbations des solutions proposées, sans réoptimisation) : la marge de 10 % absorbe un allongement de 10 % sans heure
  supplémentaire ; au-delà (+20 % ou bruit réaliste), tous les programmes génèrent des heures supplémentaires, et
  d'autant plus qu'ils remplissent le bloc. Une réduction de 6 lits rend tous les programmes non faisables ; les
  places ambulatoires ne sont pas limitantes.
- *Saturation* : le temps opératoire est la ressource limitante (432 patients en 4 semaines) ; les lits le
  deviennent sous 20 lits.

## Points transversaux

- Aucun gap d'optimalité : seuls « gain vs départ » et « écart à la meilleure solution faisable observée » sont
  publiés.
- Capacités du moteur et fonctionnalités actives du site diffèrent : le site désactive les optimisations locale et
  globale du SMA.
- La priorité d'urgence et tout transfert relèvent d'une décision humaine.
- Les patients N2, SMA et de saturation sont synthétiques ou tirés de profils ; seuls les patients saisis en
  consultation reçoivent des prédictions du ML.
- Résultats absents ou non exécutés : voir `QUESTIONS.md`.
