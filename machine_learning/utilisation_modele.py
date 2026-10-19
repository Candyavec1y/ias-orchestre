"""
=====================================================================
UTILISATION ET VALIDATION DES MODÈLES
=====================================================================
A) Validation sur le jeu de test (20 %, jamais vu) : métriques communes
   (preparation.evaluer) + exemples de cas réels et pires erreurs.
B) Modèles de PRODUCTION (.joblib) appliqués à des profils fictifs.

    python machine_learning/utilisation_modele.py
=====================================================================
"""
import argparse

import joblib
import numpy as np
import pandas as pd

import preparation as PREP

pd.set_option('display.width', 160)
pd.set_option('display.max_columns', 20)

FICHIERS_MODELES = {"clf_capacite": "clf_type_capacite.joblib", "reg_bloc": "reg_duree_bloc.joblib",
                    "reg_avant": "reg_duree_avant.joblib", "reg_apres": "reg_duree_apres.joblib"}


# =====================================================================
# A) VALIDATION EMPIRIQUE SUR LE JEU DE TEST
# =====================================================================
def valider_sur_jeu_de_test(graine: int = PREP.GRAINE_ML) -> dict:
    df = PREP.charger_et_preparer()
    m, pred, pred_lit = PREP.evaluer(df, details=True, graine=graine)
    print("=" * 70 + "\nMÉTRIQUES — jeu de test (20 %, jamais vu)\n" + "=" * 70)
    PREP.afficher_metriques(m)

    echantillon = pred.sample(n=min(15, len(pred)), random_state=graine)
    print("\n-- Cas réels : prise en charge et durée au bloc --")
    print(pd.DataFrame({
        "type_intervention": echantillon["type_intervention"].str.slice(0, 22),
        "capacite_reelle": echantillon[PREP.CIBLE_CAPACITE], "capacite_predite": echantillon["capacite_predite"],
        "bloc_h_reel": echantillon["duree_bloc_heures"].round(2), "bloc_h_predit": echantillon["bloc_h_predit"].round(2),
    }).to_string(index=False))

    print("\n-- Pires erreurs : durée au bloc (top 10) --")
    print(pred.assign(erreur_h=np.abs(pred["duree_bloc_heures"] - pred["bloc_h_predit"]))
          .sort_values("erreur_h", ascending=False)[["type_intervention", "duree_bloc_heures", "bloc_h_predit",
                                                     "erreur_h"]].head(10).to_string(index=False))
    print("\n-- Pires erreurs : nuits après l'opération, hospitalisés (top 10) --")
    print(pred_lit.assign(erreur_j=np.abs(pred_lit["duree_apres_operation"] - pred_lit["apres_j_predit"]))
          .sort_values("erreur_j", ascending=False)[["type_intervention", "duree_apres_operation", "apres_j_predit",
                                                     "erreur_j"]].head(10).to_string(index=False))
    return m


# =====================================================================
# B) MODÈLES DE PRODUCTION SUR DES CAS FICTIFS
# =====================================================================
def charger_modeles_production() -> dict:
    return {k: joblib.load(PREP.DOSSIER_MODELES / f) for k, f in FICHIERS_MODELES.items()}


def predire_patient(patient: dict, modeles: dict) -> dict:
    """Prédictions pour un patient (dict des colonnes CAT_COLS + NUM_COLS). Le score d'urgence est calculé par la
    RÈGLE du projet (preparation.regle_urgence), pas par un modèle (D8)."""
    x = pd.DataFrame([patient])[PREP.CAT_COLS + PREP.NUM_COLS]
    for c in PREP.CAT_COLS:
        x[c] = x[c].astype(str).astype('category')
    capacite = modeles["clf_capacite"].predict(x)[0]
    resultat = {
        "type_capacite_predit": capacite,
        "duree_bloc_heures_predit": round(max(0.0, float(modeles["reg_bloc"].predict(x)[0])), 2),
        "score_urgence": PREP.regle_urgence(patient.get("cim_diag_pr"), patient.get("ccam_1")),
        "duree_avant_operation_jours": 0, "duree_apres_operation_jours": 0,
    }
    if capacite == PREP.HOSPITALISE:
        resultat["duree_avant_operation_jours"] = round(max(0.0, float(modeles["reg_avant"].predict(x)[0])), 1)
        resultat["duree_apres_operation_jours"] = round(max(0.0, float(modeles["reg_apres"].predict(x)[0])), 1)
    return resultat


CAS_PRATIQUES = {
    "PTH chez patient âgé (attendu : hospitalisation, durées longues, urgence basse)": {
        "type_intervention": "Prothese Totale Hanche", "cim_diag_pr": "M16.1", "ccam_1": "NEKA020", "sexe": "1",
        "praticien": "CL", "anesth_type": "AG avec intubation", "anesth_loco_reg": "Inconnu",
        "age_annees": 78, "annee": 2026, "mois": 3, "jour_semaine": 1},
    "Arthroscopie du genou, patient jeune (attendu : ambulatoire, bloc court)": {
        "type_intervention": "Arthroscopie Genou", "cim_diag_pr": "S83.2", "ccam_1": "NFEA001", "sexe": "2",
        "praticien": "LZ", "anesth_type": "AG avec masque laryngé", "anesth_loco_reg": "Bloc coude",
        "age_annees": 24, "annee": 2026, "mois": 6, "jour_semaine": 3},
    "Intervention jamais vue à l'entraînement (attendu : le modèle répond quand même)": {
        "type_intervention": "Intervention totalement inconnue XYZ", "cim_diag_pr": "Z99.9", "ccam_1": "INCONNU",
        "sexe": "1", "praticien": "Inconnu", "anesth_type": "Inconnu", "anesth_loco_reg": "Inconnu",
        "age_annees": 50, "annee": 2026, "mois": 1, "jour_semaine": 0},
}


def tester_cas_fictifs() -> None:
    modeles = charger_modeles_production()
    print("\n" + "=" * 70 + "\nCAS FICTIFS — modèles de production (entraînés sur 100 % des données)\n" + "=" * 70)
    for description, patient in CAS_PRATIQUES.items():
        print(f"\n--- {description} ---")
        for k, v in predire_patient(patient, modeles).items():
            print(f"  {k} : {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Validation des modèles et cas fictifs")
    ap.add_argument("--graine", type=int, default=PREP.GRAINE_ML)
    a = ap.parse_args()
    valider_sur_jeu_de_test(a.graine)
    tester_cas_fictifs()
