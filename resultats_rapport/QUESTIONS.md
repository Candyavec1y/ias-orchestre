# Questions, défauts constatés et éléments non produits

Aucun défaut n'a été corrigé pendant les campagnes (le code est figé au commit `d8fbf35`). Chaque point indique les
expériences touchées.

## Décisions de l'équipe (réponses du 20/10/2026), appliquées aux résultats

| Point | Décision | Conséquence dans ce dossier |
|---|---|---|
| 1. Départ N2 non faisable : dépassement de vacation pénalisé dans F2 mais refusé par le validateur | Pendant la recherche, les dépassements sont autorisés avec un poids élevé ; **à la fin, seules les solutions faisables sont proposées** (contrainte dure) | Une exécution dont la solution finale n'est pas faisable compte comme « aucune solution proposée » ; scores, IC, tests, profils de ressources et robustesse portent sur les solutions proposées ; le glouton est le départ (référence, non proposé) |
| 2. Budget légèrement dépassé par les modes à population | Ne pas en tenir compte | Temps réels toujours publiés, sans réserve dans les comparaisons |
| 3. Séparation ML par séjour (35,5 % de recouvrement de patients) | L'équipe va revoir le ML | Résultats ML marqués provisoires |
| 4. Convergence N2 sur le score de recherche | L'équipe refait le score | Résultats N2 marqués provisoires |
| 5. Exécutions parallèles sur cœurs hétérogènes | Accepté | Aucun changement |
| Publication des solutions N2 non faisables | Ignorer | Question retirée (elles restent dans les CSV bruts, colonne `faisable`) |
| Droits de diffusion des données hospitalières | Données anonymisées : pas de problème selon l'équipe | Question retirée ; seuls des agrégats sont produits ici |

À noter pour le point 1 : le code actuel ne garantit pas encore cette règle pour chaque méthode (une recherche peut
se terminer sur une solution non faisable sans garder la meilleure solution faisable rencontrée) ; seule la
sélection finale entre modes d'hybridation (`_meilleur_hybride`) préfère une solution faisable. La règle est donc
appliquée ici à l'analyse ; elle reste à implémenter dans les métaheuristiques avec la refonte du score.

## Point encore ouvert

6. **Plantage du SMA (KeyError `chir_7`).** Dans un scénario aléatoire de surcharge, la régulation interroge
   l'agent d'un chirurgien du service qui n'a aucune vacation sur l'horizon de 2 semaines (n° 7, DS) : aucun agent
   n'est créé pour lui, mais il figure parmi les chirurgiens compétents. Le site (52 semaines connues) est moins
   exposé, sans que cela soit démontré. *Touché* : H (les exécutions concernées sont marquées ÉCHEC dans
   `sma_scenarios.csv`, colonne `echec`). *À corriger* : ne proposer que les chirurgiens qui ont un agent.

## Non disponible (NON DISPONIBLE) ou non exécuté

| Élément demandé | Statut | Raison |
|---|---|---|
| SMA « programme figé » et « régulation simple » | NON DISPONIBLE | le moteur n'a pas de mode sans reprogrammation ni de régulateur « premier créneau » ; les écrire serait une nouvelle fonctionnalité métier |
| Lits matin / soir, admissions du soir | NON DISPONIBLE | le modèle n'a pas d'heure d'admission (décompte par nuitée, sortie à midi) ; seules les nuitées, sorties et admissions du jour sont mesurées |
| Rotation intra-journalière des places | PARTIEL | mesurée par demi-journée (matin / après-midi), pas à l'heure |
| Gap d'optimalité | NON DISPONIBLE | aucune solution optimale ni borne valide ; on publie « gain vs départ » et « écart à la meilleure solution faisable observée » |
| Chaînage N1 → N2 sur v28 | NON DISPONIBLE | le N1 ne travaille que sur l'instance d'étude fictive (D6) |
| Séparation ML par patient | NON EXÉCUTÉ | à faire par l'équipe (revue du ML) ; recouvrement mesuré |
| Temps d'entraînement des modèles déployés | NON EXÉCUTÉ | seul l'entraînement des 4 copies d'évaluation (80 %) est mesuré |
| Front non dominé, sensibilité aux poids, ablations, référence exacte (P2) | NON EXÉCUTÉ | hors P0 / P1 |
| Marges opératoires 0 / 5 / 15 / 20 % | NON EXÉCUTÉ | la marge (`TAUX_MARGE_VACATION`) est une constante du projet ; la robustesse à la marge est approchée par la perturbation des durées (×1,1 = consommation de la marge) |
| Nuits / week-end / garde dans les scénarios | PARTIEL | seuls les scénarios du moteur et les combinaisons de `h_sma.py` ; la garde intervient dans les scénarios chargés |
