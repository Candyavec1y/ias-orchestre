# Tâche H — SMA : résumé

Source (rejoué sur la branche v3, avec `solution_finale` côté SMA) : `sma_scenarios.csv` (une ligne par scénario × stratégie × graine), `sma_evenements_agreges.csv` (temps
réel par type d'événement), script `scripts/h_sma.py`, commit `d8fbf35`. Planning v28, 2 semaines à partir du
12/10/2026, programme initial glouton commun (181 interventions), capacités 30 lits / 3 réserve / 20 places,
graine Mesa 42. **Les durées « simulées » (attentes, heures) relèvent de l'horloge du SMA ; les temps de calcul
sont des temps réels.**

## Stratégies comparées (événements identiques)

| Code | Configuration | Disponibilité |
|---|---|---|
| — | Programme figé | NON DISPONIBLE (pas de mode sans reprogrammation dans le moteur) |
| — | Régulation simple « premier créneau » | NON DISPONIBLE |
| S_CN | Contract Net sans métaheuristique (**configuration du site**) | mesuré |
| S_LOC | + optimisation locale TABOU seul (0,02 s par créneau) | mesuré |
| S_GLOB | + optimisation globale memetique (1 s par réoptimisation) | mesuré |
| S_LOC_GLOB | locale + globale (défaut du moteur) | mesuré |

## Résultats sur les 21 scénarios déterministes (13 du projet + 8 combinaisons de `h_sma.py`)

| Stratégie | Urgences | Dans le délai | Transferts proposés | Décalés | Reportés à un autre jour | Repris par un confrère | Liste d'attente | Planning conservé (moy.) | Incohérences | Temps réel cumulé |
|---|---|---|---|---|---|---|---|---|---|---|
| S_CN | 23 | 21 | 1 | 26 | 54 | 57 | 8 | 97,3 % | 0 | 6,2 s |
| S_LOC | 23 | 21 | 1 | 27 | 54 | 57 | 8 | 97,3 % | 0 | 10,8 s |
| S_GLOB | 23 | 21 | 1 | 48 | 49 | 72 | 5 | 96,7 % | 0 | 64,8 s |
| S_LOC_GLOB | 23 | 21 | 1 | 51 | 47 | 69 | 4 | 96,7 % | 0 | 69,3 s |

- **Urgences** : les quatre stratégies traitent les urgences de la même façon (même nombre dans le délai, mêmes
  attentes, sauf dans deux scénarios où l'optimisation globale modifie l'attente moyenne : `urgence_vitale_surcharge` 72,5 → 82,5 min et `journee_multi_aleas` 460 → 390 min, en S_LOC_GLOB). Les 2 urgences hors délai sont : l'ischémie vasculaire (spécialité non couverte →
  **transfert proposé**, décision humaine requise, `chirurgien_absent`) et une urgence de la journée surchargée avec
  panne du monte-lit (`urgence_vitale_surcharge`, confiée à la garde).
- **Optimisation globale** : elle vide davantage la liste d'attente (8 → 4 ou 5 patients) et réduit un peu les
  reports à un autre jour (54 → 47 ou 49), au prix de **plus de patients décalés** (26 → 48-51), de plus de reprises
  par un confrère (57 → 69-72) et d'un temps de calcul multiplié par environ 11 (6 s → 65-69 s cumulées). C'est un
  compromis, pas une amélioration nette.
- **Optimisation locale seule** : quasiment aucun effet mesurable par rapport à S_CN (1 décalé de plus, 65 minutes
  de décalage en moins), pour un temps de calcul presque doublé.
- **Cohérence** : 0 erreur au contrôle indépendant du SMA dans toutes les exécutions qui ont abouti.

## Scénarios aléatoires (5 graines, mêmes événements pour les 4 stratégies)

| Scénario | Exécutions abouties | Urgences | Dans le délai | Attente moyenne (S_CN) |
|---|---|---|---|---|
| Semaine normale (1 urgence / jour en moyenne) | 5 / 5 graines | 22 | 22 | 221 min (simulées) |
| Semaine en surcharge (3 urgences / jour + 2 pannes) | **2 / 5 graines** | 28 | 28 | 341 min (simulées) |

**Échec du moteur** : avec les graines 2, 3 et 4 de la semaine en surcharge, la simulation s'arrête sur une
`KeyError: 'chir_7'` pour les 4 stratégies : un chirurgien du service sans vacation sur l'horizon de 2 semaines est
proposé comme compétent, mais aucun agent n'existe pour lui (`QUESTIONS.md`, point 6). Ces exécutions sont
marquées ÉCHEC et **ne sont pas comptées comme des succès**.

## Cas particuliers observés

- `journee_multi_aleas` : l'ischémie vasculaire est vue par HA, chirurgien du planning disponible ce jour-là : elle
  est opérée dans le délai, sans proposition de transfert. Le transfert n'est proposé que lorsqu'aucun chirurgien
  compétent n'est disponible à temps (cas `chirurgien_absent`, vendredi).
- `urgence_lits_satures` (15 lits fermés) : l'urgence vitale est opérée en 15 min, grâce à la réserve ; 9 patients
  programmés sont reportés et 2 restent en liste d'attente.
- `lits_indisponibles` et `absence_lits` : 8 patients reportés ; jusqu'à 3 alertes humaines (patients prioritaires
  repoussés).

## Temps réel de régulation par événement (`sma_evenements_agreges.csv`)

| Stratégie | Arrivée d'urgence : médiane / P95 / max | Autres événements (médiane) |
|---|---|---|
| S_CN (site) | 0,004 s / 0,031 s / 0,046 s | 0,001-0,019 s |
| S_LOC_GLOB | 1,21 s / 1,84 s / 2,32 s | 1,03-1,10 s (dominé par la réoptimisation globale de 1 s) |

Reconstruction de l'état du site (rejeu du SMA, sans événement) : 0,25 s (`temps.csv`).

## Figures

Paires de Gantt avant / après (configuration du site, patients synthétiques) : `figures/sma_gantt_urgence_panne_*`
(panne grisée), `sma_gantt_surcharge_*` (4 urgences + panne, salle de garde), `sma_gantt_prolongation_*`,
`sma_gantt_lits_*` (13 et 14/10). PNG uniquement : le tracé est celui du moteur (`BlocOperatoire.tracer_gantt`).

## Limites

- Programme figé et régulation simple non disponibles : le gain du SMA par rapport à une absence de
  régulation n'est **pas mesuré**.
- Un seul programme initial (glouton) et une seule graine Mesa ; les scénarios déterministes sont des cas tests
  choisis, pas un échantillon représentatif.
- Les transferts sont **proposés** ; aucun n'est validé ni réalisé dans la simulation.
