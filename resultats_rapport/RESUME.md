# OR'CHESTRE — Résumé des résultats (campagnes P0 et P1)

Commit `d8fbf35`, Apple M2, budget de 10 s par exécution de métaheuristique. Toutes les valeurs proviennent des
fichiers mesurés de ce dossier (voir `manifest.json`). Statuts : MESURÉ sauf indication contraire. Les anciennes
valeurs des soutenances ne sont pas reprises.

## 1. Machine learning (4 modèles ; urgence = règle)

Jeu de test de 2 896 séjours (séparation 80 / 20 **par séjour**, 35,5 % des séjours de test avec un patient vu à
l'entraînement).

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
| memetique | 920 ± 48 | 900 | 47,4 % |
| AGS>RS>TABOU | 925 ± 49 | 900 | 47,1 % |
| TABOU seul | 960 ± 32 | 950 | 45,1 % |
| AGS seul | 1 005 ± 50 | 950 | 42,6 % |

La meilleure valeur observée (900) n'est pas une borne prouvée : aucun gap d'optimalité n'est calculé.

## 3. Niveau 2 sur le planning réel v28 (4 semaines + 3 semaines de report)

**Cohorte de référence** (421 patients, charge 99 % de la capacité utile, 10 graines). Départ commun (glouton +
placement des restants) : F2 = 8 265, **non faisable** (18 minutes au-delà de la capacité utile d'une vacation).

| Méthode | Faisable | F2 commun moyen [IC 95 %] | Gain vs départ | Patients reportés | Occupation bloc |
|---|---|---|---|---|---|
| premier créneau (adaptateur) | 1 / 1 | 5 484 | 33,6 % | 36 | 88,0 % |
| RS seul | 10 / 10 | **3 344** [3 220 ; 3 467] | 59,5 % | 23,2 | 92,9 % |
| AGS>RS>TABOU | 8 / 10 | 3 593 [3 465 ; 3 721] | 56,5 % | 25,3 | 92,0 % |
| memetique | 10 / 10 | 3 823 [3 696 ; 3 951] | 53,7 % | 28,2 | 91,1 % |
| RS>AGS>TABOU | 9 / 10 | 3 905 [3 831 ; 3 979] | 52,8 % | 28,0 | 90,9 % |
| TABOU seul | 9 / 10 | 3 956 [3 823 ; 4 089] | 52,1 % | 33,7 | 90,5 % |
| AGS seul | 7 / 10 | 5 708 [5 591 ; 5 825] | 30,9 % | 65,4 | 85,2 % |

**Test fixé a priori** (memetique contre chaque méthode seule, Wilcoxon apparié, Holm) : memetique est **moins bon
que RS seul** (10 graines sur 10 ; p corrigé = 0,006), **meilleur qu'AGS seul** (10 / 10 ; p = 0,006), et non
différent de TABOU seul au seuil de 5 % (p = 0,13 ; ce n'est pas une preuve d'équivalence).

**Charge** (3 cohortes × 3 graines) : à 70 % toutes les méthodes sont faisables et proches (écart à la meilleure
solution faisable ≤ 6 %) ; à 85 %, le taux de faisabilité des métaheuristiques tombe à 56-67 % (le glouton reste
faisable, premier créneau 33 %) ; à 100 %, à 11-33 % (glouton 0 %) ; à 115 %, **aucune solution n'est faisable**. Toutes les violations sont des dépassements de la capacité utile d'une vacation, que F2
pénalise sans les interdire.

**Budget** (2 / 5 / 10 / 20 s, 3 graines) : RS seul est le meilleur à tous les budgets ; à 2 s, TABOU seul et AGS seul
ne produisent aucune solution faisable.

## 4. Coordination bloc / lits / places (cohorte de référence)

Les méthodes qui remplissent le plus le bloc (RS seul : 92,9 %) ont le score lits le plus élevé (982) ; AGS seul
remplit moins le bloc (85,2 %) mais a le plus faible pic de lits (23 contre 25) et la plus faible composante lits
(797). Aucun lit n'est utilisé au-delà des 27 lits programmables. Places ambulatoires : pic de 6 à 11 patients par
demi-journée pour 20 places, jamais saturées. Délai moyen entre la date au plus tôt et l'intervention : 3,5 jours
(RS seul) à 6,7 jours (glouton).

## 5. Saturation et robustesse

- **Saturation** (programme vide, patients au profil réel, SMA) : 432 patients opérés en 4 semaines (426 à 437 selon
  la graine) ; 95,1 % de la capacité utile ; la ressource limitante est le **temps opératoire**. Avec 20 lits au lieu
  de 30 : 13 jours de lits pleins, 440 patients opérés mais une occupation utile plus faible (94,0 %) : davantage
  d'ambulatoires, plus courts.
- **Durées +10 %** : la marge de 10 % absorbe l'allongement (0 minute au-delà de la durée totale des vacations),
  mais aucun programme n'est plus faisable au sens de la capacité utile. **Durées +20 %** : 76 à 95 vacations en
  heures supplémentaires selon la méthode, jusqu'à 1 232 minutes (RS seul). **Bruit lognormal σ = 0,25** : 431 à
  533 minutes d'heures supplémentaires en moyenne (17 à 21 vacations) ; les programmes les plus remplis sont les plus exposés.
- **Lits réduits à 24** : tous les programmes deviennent non faisables (2 à 9 nuits en dépassement) ; **places à
  15** : aucun effet.

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
