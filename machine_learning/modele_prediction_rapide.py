"""
=====================================================================
MODÈLES PRÉDICTIFS — ENTRAÎNEMENT (HistGradientBoosting)
=====================================================================
Un modèle par cible (HistGradientBoosting, natif scikit-learn : gère les
variables catégorielles et les valeurs manquantes, entraînement rapide) :

    clf_type_capacite.joblib   ambulatoire / hospitalisation
    reg_duree_bloc.joblib      durée au bloc (heures)
    reg_duree_avant.joblib     nuits avant l'opération  (hospitalisés)
    reg_duree_apres.joblib     nuits après l'opération  (hospitalisés)

Le score d'urgence n'est PAS appris : c'est une règle (preparation.regle_urgence, D8).

Évaluation : split UNIQUE 80 / 20 stratifié (preparation.evaluer), puis
modèles finaux entraînés sur 100 % des données.

    python machine_learning/modele_prediction_rapide.py                    # évalue et enregistre les modèles
    python machine_learning/modele_prediction_rapide.py --evaluer-seulement
=====================================================================
"""
import argparse
import time

import joblib

import preparation as PREP


def entrainer_modeles_finaux(df, graine: int = PREP.GRAINE_ML) -> dict:
    """Modèles de production, entraînés sur 100 % des données (hospitalisés seulement pour les nuits)."""
    x = PREP.vers_categories(df[PREP.CAT_COLS + PREP.NUM_COLS])
    lit = df[df[PREP.CIBLE_CAPACITE] == PREP.HOSPITALISE]
    x_lit = PREP.vers_categories(lit[PREP.CAT_COLS + PREP.NUM_COLS])
    return {
        "clf_type_capacite": PREP.modele(True, graine=graine).fit(x, df[PREP.CIBLE_CAPACITE]),
        "reg_duree_bloc": PREP.modele(False, graine=graine).fit(x, df["duree_bloc_heures"]),
        "reg_duree_avant": PREP.modele(False, graine=graine).fit(x_lit, lit["duree_avant_operation"]),
        "reg_duree_apres": PREP.modele(False, graine=graine).fit(x_lit, lit["duree_apres_operation"]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entraînement des modèles de prédiction")
    ap.add_argument("--graine", type=int, default=PREP.GRAINE_ML)
    ap.add_argument("--evaluer-seulement", action="store_true", help="n'enregistre pas les modèles")
    a = ap.parse_args(argv)
    t0 = time.time()
    df = PREP.charger_et_preparer()
    print(f"{len(df)} séjours utilisables.\n")
    PREP.afficher_metriques(PREP.evaluer(df, graine=a.graine))
    if a.evaluer_seulement:
        return
    PREP.DOSSIER_MODELES.mkdir(parents=True, exist_ok=True)
    for nom, m in entrainer_modeles_finaux(df, a.graine).items():
        joblib.dump(m, PREP.DOSSIER_MODELES / f"{nom}.joblib")
    print(f"\nTerminé en {time.time() - t0:.1f} s. Modèles enregistrés dans {PREP.DOSSIER_MODELES}")


if __name__ == "__main__":
    main()
