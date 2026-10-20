# Tâche C — Machine learning : résumé

Source : `ml_resultats.csv`, `donnees_agregees/ml_*.csv` (script `scripts/c_ml.py`, commit `d8fbf35`). Toutes les
valeurs sont MESURÉES sur le jeu de test, sauf mention contraire. Aucune donnée individuelle n'est exportée.

## Données et protocole

| Élément | Valeur |
|---|---|
| Séjours dans le CSV | 14 649 |
| Séjours après préparation | 14 477 (172 exclus : dates ou durées manquantes ou négatives, durée de bloc nulle) |
| Mode de prise en charge | 7 957 ambulatoires, 6 520 hospitalisés |
| Patients distincts | 11 015 |
| Séparation | **par séjour** (et non par patient), 80 / 20 stratifiée sur le mode de prise en charge, graine 42 |
| Entraînement / test | 11 581 / 2 896 séjours (dont 1 304 hospitalisés au test) |
| **Recouvrement de patients** | 1 029 séjours du test (35,5 %) appartiennent à un patient qui a aussi un séjour à l'entraînement : **risque de fuite**, les métriques peuvent être optimistes pour de nouveaux patients |
| Variables | 11 : type d'intervention, CIM-10 principal, CCAM 1, sexe, praticien, type d'anesthésie, ALR, âge, année, mois, jour de la semaine |
| Modèles | HistGradientBoosting (profondeur 6, taux 0,08, 200 itérations, arrêt précoce) |

Les modèles évalués sont des **copies réentraînées en mémoire** sur la partie entraînement, avec la préparation et
les hyperparamètres du projet. Les modèles déployés sont entraînés sur 100 % des séjours ; pendant le nettoyage
(lot 7), ces mêmes modèles réentraînés sur toutes les données ont donné des prédictions identiques aux modèles
déployés. Les `.joblib` n'ont pas été modifiés.

## Performances (jeu de test)

| Modèle | n | Métrique du modèle | Référence simple (apprise sur l'entraînement) |
|---|---|---|---|
| Durée au bloc | 2 896 | R² 0,670 ; MAE 14,8 min ; RMSE 21,8 min ; erreur absolue médiane 10,1 min, P90 32,4 min, P95 43,3 min | médiane globale : R² −0,03, MAE 29,2 min ; médiane par type d'intervention : R² 0,45, MAE 19,1 min |
| Mode de prise en charge | 2 896 | accuracy 0,925 ; F1 ambulatoire 0,933, hospitalisé 0,915 ; Brier 0,056 | classe majoritaire (ambulatoire) : accuracy 0,550 |
| Nuits avant (hospitalisés) | 1 304 | R² 0,03 ; MAE 0,26 ; RMSE 2,48 ; erreur ≤ 1 nuit 98,0 % | médiane (0 nuit) : R² −0,01 ; MAE 0,29 ; ≤ 1 nuit 98,3 % |
| Nuits après (hospitalisés) | 1 304 | R² 0,695 ; MAE 0,54 ; RMSE 0,83 ; ≤ 1 nuit 85,1 % ; ≤ 2 nuits 96,8 % | médiane : R² −0,06 ; MAE 1,13 ; ≤ 1 nuit 77,9 % |

Matrice de confusion (lignes : réel, colonnes : prédit) : ambulatoires 1 511 / 81 ; hospitalisés 135 / 1 169. Les
erreurs dominantes sont donc des hospitalisés prédits ambulatoires (10,4 % des hospitalisés), l'erreur la plus
coûteuse pour les lits.

**Sous-estimation de la durée au bloc** : 43,6 % des séjours, de 17,2 min en moyenne. Elle augmente avec la durée
réelle : interventions de plus de 2 h (n = 365) sous-estimées dans 80,5 % des cas, de 26,7 min en moyenne (erreur
signée) ; moins de 1 h (n = 1 167) surestimées de 7,8 min en moyenne. Par mode : MAE 11,8 min en ambulatoire,
18,4 min en hospitalisation. Le détail par type d'intervention (n ≥ 100) est dans `ml_erreurs_sous_groupes.csv`.

**Nuits avant** : le modèle n'apporte presque rien par rapport à la médiane (0 nuit) : R² 0,03 contre −0,01, et une
part à ±1 nuit légèrement plus faible (98,0 % contre 98,3 %). Le RMSE de 2,5 nuits vient de rares séjours longs
avant l'intervention.

## Score d'urgence (règle, pas un modèle)

Le score 1-10 est calculé par une **règle déterministe** à partir du CIM-10 principal et du premier acte CCAM
(`preparation.regle_urgence`), converti en priorité proposée 1-4, que le médecin valide ou corrige. Il n'a ni R², ni
validation clinique. Distribution sur les 14 477 séjours : score 1 → 15,2 % ; 3 → 58,2 % ; 6 → 0,2 % ; 8 → 12,1 % ;
9 → 14,3 % (priorité 4 : 26,4 %).

## Temps (temps réel, Apple M2)

Chargement des 4 modèles déployés : 0,055 s ; prédiction unitaire (4 modèles) : médiane 9,6 ms, P95 11,6 ms (n =
50) ; préparation des données : 0,26 s ; entraînement des 4 copies et prédiction du test : 1,2 s.

## Non réalisé

- Séparation par patient : NON EXÉCUTÉ (ce n'est pas le protocole du projet). Le recouvrement est mesuré
  ci-dessus ; une réévaluation avec séparation par patient est recommandée (`QUESTIONS.md`).
- Sensibilité du planning aux erreurs de durée provenant du ML : voir la tâche G (perturbation des durées) ; les
  cohortes N2 ne proviennent pas du ML (générateur synthétique `generer_patients_etude`).

Figures : `figures/ml_reel_predit`, `figures/ml_residus_confusion`, `figures/ml_calibration` (PNG 300 dpi et PDF).
Les nuages réel / prédit sont des densités (hexbin) ; les cases de moins de 5 séjours sont masquées pour ne montrer
aucun point individuel.
