# Questions, défauts constatés et éléments non produits

Aucun défaut n'a été corrigé pendant les campagnes (le code est figé au commit `d8fbf35`). Chaque point indique les
expériences touchées.

## Défauts ou particularités qui touchent l'interprétation

1. **Départ N2 non faisable.** Le glouton commun suivi de `placer_restants` (`hybridation.py`) place chaque patient
   restant dans la vacation qui dégrade le moins le score, même au-delà de la capacité utile. F2 compte ce
   dépassement comme une pénalité (100 par minute) alors que le validateur le déclare violation. Une méthode qui
   part de cette solution peut donc rendre un très bon score sans être faisable. *Touché* : E, F, G (les écarts
   sont calculés par rapport aux solutions faisables ; la faisabilité est publiée à part). *À trancher* : faire du
   dépassement de vacation une contrainte dure dans la recherche, ou un poids bien plus élevé.
2. **Budget dépassé par RS>AGS>TABOU.** Les 4 recherches locales de départ ne s'interrompent pas exactement au
   budget (2,9 s pour 2 s dans le pilote). Le temps réel de chaque exécution est publié ; la comparaison « à budget
   égal » est donc approximative pour ce mode. *Touché* : E, I.
3. **Séparation ML par séjour.** 35,5 % des séjours du test ont un patient vu à l'entraînement : risque de fuite,
   métriques possiblement optimistes. *À faire* : réévaluer avec une séparation par patient (`GroupShuffleSplit`)
   dans une copie isolée. *Touché* : C.
4. **Convergence N2 sur le score de recherche.** L'historique enregistré par le projet est celui du score optimisé
   (F2 + pénalité de report), pas F2 commun : la figure de convergence N2 utilise donc le score de recherche.
5. **Exécutions parallèles.** 4 processus sur un M2 (4 cœurs performance + 4 efficacité) : une exécution peut avoir
   tourné sur un cœur plus lent. L'ordre des tâches a été mélangé et le nombre d'évaluations est publié.
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
| Séparation ML par patient | NON EXÉCUTÉ | hors protocole du projet ; recouvrement mesuré |
| Temps d'entraînement des modèles déployés | NON EXÉCUTÉ | seul l'entraînement des 4 copies d'évaluation (80 %) est mesuré |
| Front non dominé, sensibilité aux poids, ablations, référence exacte (P2) | NON EXÉCUTÉ | hors P0 / P1 |
| Marges opératoires 0 / 5 / 15 / 20 % | NON EXÉCUTÉ | la marge (`TAUX_MARGE_VACATION`) est une constante du projet ; la robustesse à la marge est approchée par la perturbation des durées (×1,1 = consommation de la marge) |
| Nuits / week-end / garde dans les scénarios | PARTIEL | seuls les scénarios du moteur et les combinaisons de `h_sma.py` ; la garde intervient dans les scénarios chargés |

## Points à valider par l'équipe

- Publier ou non les résultats N2 « non faisables » dans le rapport (ils sont dans les CSV, signalés).
- Les données hospitalières sont dans un dépôt public (voir `interface/CHOIX.md` § 10) : seuls des agrégats sont
  produits ici, mais la question des droits de diffusion reste ouverte.
