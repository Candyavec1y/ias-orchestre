# Tâche I — Temps de calcul : résumé

Source : `temps.csv`, `donnees_agregees/temps_pour_seuil.csv`, figure `figures/temps_debit_n2`. Temps **réels**
(`perf_counter`) sur Apple M2, 8 Gio (`environnement.md`). Les durées simulées du SMA ne sont pas des temps de
calcul.

## Métaheuristiques (budget alloué : 10 s)

| Niveau | Méthode | Temps réel moyen | Maximum | Dépassement max. du budget |
|---|---|---|---|---|
| N1 | RS seul / TABOU seul | 10,00 s | 10,00 s | < 0,1 % |
| N1 | AGS seul, memetique, AGS>RS>TABOU, RS>AGS>TABOU | 10,16-10,18 s | 10,20 s | 1,7-2,0 % |
| N2 | RS seul / TABOU seul | 10,00-10,02 s | 10,06 s | ≤ 0,6 % |
| N2 | AGS seul, memetique, AGS>RS>TABOU | 10,34-10,35 s | 10,38 s | 3,6-3,8 % |
| N2 | RS>AGS>TABOU | 10,42 s | 10,49 s | 4,9 % |
| N2 | glouton (départ) / premier créneau | 0,45 s | — | sans budget |

Les temps réels sont publiés tels que mesurés ; à la demande de l'équipe, le léger dépassement du budget par les
modes à population n'est pas pris en compte dans les comparaisons.

**Nombre d'évaluations** : publié dans `n1_resultats.csv` / `n2_resultats.csv`, mais **non comparable entre
méthodes** : les évaluations servies par le cache de `ProblemeHybrideN2.cout` et les évaluations incrémentales des
voisinages ne sont pas comptées de la même façon (AGS seul : environ 9 700 évaluations comptées contre 0,8 à
1,8 million pour les autres en N2).

## Temps pour atteindre un seuil (fixé avant l'analyse)

Seuil : score de recherche ≤ 1,05 × meilleur score de recherche d'une solution faisable de la cohorte de
référence. Seul RS seul l'atteint, dans 3 exécutions sur 10 (médiane 9,4 s) ; aucune autre méthode ne l'atteint en
10 s. Le seuil de 5 % s'est révélé trop strict pour discriminer les autres méthodes ; il n'a pas été modifié après
coup.

## Autres composants (médianes)

| Composant | Temps réel |
|---|---|
| Chargement des 4 modèles ML déployés | 0,055 s |
| Prédiction ML unitaire (4 modèles) | 9,6 ms (P95 11,6 ms) |
| Préparation des données ML / entraînement des 4 copies d'évaluation | 0,26 s / 1,2 s |
| Validateur indépendant N2 (instance de référence, 7 semaines) | 0,5 ms |
| Évaluation complète F2 | 0,5 ms |
| Glouton multi-départ N2 (40 essais) | 0,38 s |
| Génération d'une instance v28 de 4 semaines | 0,58 s au premier appel, 0,004 s ensuite (planning en cache) |
| Calcul du programme du site (glouton) | 0,13 s |
| Reconstruction de l'état du site (rejeu SMA, sans événement) | 0,25 s |
| SMA, configuration du site : traitement d'une arrivée d'urgence | 0,004 s (P95 0,031 s) |
| SMA avec optimisation locale + globale : arrivée d'urgence | 1,19 s (P95 1,89 s, max 2,22 s) |
| Étude de saturation (4 semaines, une variante) | 4 à 34 s |

## Compatibilité avec les usages

- Consultation : prédiction (10 ms) et rejeu de l'état (0,25 s) sont compatibles avec une saisie interactive.
- Régulation des urgences : moins de 0,05 s dans la configuration du site ; environ 1 à 2 s par événement avec les
  optimisations (dominées par le budget de 1 s de la réoptimisation globale).
- Recalcul du programme : 10 s par méthode (budget du site).
