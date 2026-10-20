# Environnement d'exécution

- Commit : `eba3d313742f7e471418be067359eb0e32805363` (branche `v3`)
- État git au lancement : propre (hors resultats_rapport/)
- Python : 3.13.9 (/opt/anaconda3/bin/python)
- OS : macOS-27.0.1-arm64-arm-64bit-Mach-O
- CPU : Apple M2, 8 cœurs logiques (4 performance + 4 efficacité)
- RAM : 8 Gio
- Mesure du temps : `time.perf_counter()` (temps réel écoulé, horloge monotone) ; les budgets des métaheuristiques sont des budgets de temps réel.

## Bibliothèques

| Paquet | Version |
|---|---|
| numpy | 2.3.5 |
| pandas | 2.3.3 |
| scikit-learn | 1.7.2 |
| scipy | 1.16.3 |
| mesa | 3.5.1 |
| matplotlib | 3.10.6 |
| streamlit | 1.51.0 |
| joblib | 1.5.2 |

## Empreintes SHA-256 des fichiers utilisés

| Fichier | SHA-256 |
|---|---|
| `commun/parametres.py` | `3cef2162c7bf4fc149a70ae948763042699a5162e147981594447295b72600f6` |
| `commun/structures_communes.py` | `109bff5c663b42ae86dc74a814b20522ec09bb557f1ffa0640415aee7f34bc80` |
| `commun/validation.py` | `c7bb59f4ed7f9175130ae6cc16d88d8421aa2d7b5fd6644c76d0a3b4acc6edd5` |
| `metaheuristiques/hybridation.py` | `fe91b700ca1825e7aea7451f55ee10215c58173b9da0c1e7e4b4835396c792b4` |
| `metaheuristiques/sorties.py` | `151b71e2d78d8f2a695752e4037eab85756baa529139c64bbfe3ced3beaac2e5` |
| `planning_vacations/planning_vacations_v28.py` | `bf42de34012968bc485731d132474a3582cb88bd57cd37aab4b6091c2a19a797` |
| `sma/sma_urgences.py` | `f1915a23f8ab176d01d3f82894578ffe416abcc0bc94ea9d32327bfe18fec05c` |
| `sma/optimisation_sma.py` | `ab567f3d478b725f55d66040a431cdab2f43c52262d115e10f12c09a5a6002ce` |
| `sma/metaheuristiques_sma.py` | `c475a565db1aa986407476a98621d85449315856d034d525fd9ca0bfdc59bd73` |
| `sma/scenarios_sma.py` | `77ae568d9a12e8784a3913c6412fbe6de04aabb576fd3a59523da749e4f14822` |
| `machine_learning/preparation.py` | `434cec7d1df2bf570c108ba0ddf52a9ab56627bd9d05a7b7f43607d8889c71da` |
| `machine_learning/modele_prediction_rapide.py` | `ebdd6b67e3b8e6a1f5160d8559778fe0d88ea7034e8fe38fb8b4cd9d15a5dfbd` |
| `machine_learning/utilisation_modele.py` | `823804111f9212006e57156c5f5f6b2ee825939ea4bcd32ddb1657827839898e` |
| `machine_learning/donnees_hospitalieres.csv` | `6f8556012f4bec8e696890535c3ae31ea72090464fb4d10eed5f49880add700e` |
| `machine_learning/outputs/models_rapide/clf_type_capacite.joblib` | `37f17c40f87bc33bae32edecd1202d08053f86fff06ff32fb5779d97fec60491` |
| `machine_learning/outputs/models_rapide/reg_duree_bloc.joblib` | `0dd450905cb6982f01b71786f069b1272bc3bd02d828800811ebfac4c82321ac` |
| `machine_learning/outputs/models_rapide/reg_duree_avant.joblib` | `0f6651eb3cac3a05db07edd2deddaaf2559b800fddfcbd4422e6e0951b3cc9b6` |
| `machine_learning/outputs/models_rapide/reg_duree_apres.joblib` | `64398c2753982e0cde11187d999c754b78356757a91c91e6a2136c8cd8b4f20b` |
| `interface/tests/saturation.py` | `a1b58306285424580d1784b9f4d4171a0eaa86176d46b53657d97204e4c26e4f` |
