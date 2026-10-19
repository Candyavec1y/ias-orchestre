"""
=====================================================================
VALIDATION DES MODÈLES SUR DES CAS PRATIQUES — VERSION AUTONOME
=====================================================================
Ce fichier ne dépend d'AUCUN autre fichier maison (pas d'import de
modeles_prediction_rapide) : tout le code nécessaire est inclus ici.
Tu peux le mettre où tu veux, il suffit d'ajuster les 2 chemins juste
en dessous (RAW_PATH et MODELES_DIR).

A) On réentraîne des modèles "de test" sur 80% des données (train),
   puis on les confronte aux 20% restants (test), jamais vus.
B) On charge les modèles de production déjà sauvegardés (.joblib) et
   on les fait tourner sur des profils de patients fictifs.
=====================================================================
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from datetime import datetime

from sklearn.model_selection import train_test_split
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score,
    accuracy_score, f1_score, confusion_matrix,
)

# =====================================================================
# >>> À ADAPTER À TON PC <<<
# =====================================================================
RAW_PATH = "donnees_hospitalieres.csv"
MODELES_DIR = Path("outputs/models_rapide")
# =====================================================================

RANDOM_STATE = 42
CAT_COLS = ["type_intervention", "cim_diag_pr", "ccam_1", "sexe",
            "praticien", "anesth_type", "anesth_loco_reg"]
NUM_COLS = ["age_annees", "annee", "mois", "jour_semaine"]

pd.set_option('display.width', 160)
pd.set_option('display.max_columns', 20)


# =====================================================================
# Recherche de colonnes
# =====================================================================
def trouver_colonne(mots_cles, df, min_match=None):
    if min_match is None:
        min_match = len(mots_cles)
    mots_cles_nettoyes = [
        mot.lower()
        .replace('è', 'e').replace('é', 'e').replace('ê', 'e')
        .replace('à', 'a').replace('â', 'a').replace('ï', 'i')
        .replace('î', 'i').replace('ô', 'o').replace('û', 'u').replace('ç', 'c')
        .replace(' ', '_').replace('(', '').replace(')', '')
        for mot in mots_cles
    ]
    for col in df.columns:
        col_nettoyee = col.lower().replace(' ', '_').replace('(', '').replace(')', '')
        matches = sum(1 for mot in mots_cles_nettoyes if mot in col_nettoyee)
        if matches >= min_match:
            return col
    return None


def limiter_cardinalite(serie, max_categories=200):
    top = serie.value_counts().nlargest(max_categories).index
    return serie.where(serie.isin(top), other="Autre")


# =====================================================================
# Chargement + préparation
# =====================================================================
def charger_et_preparer(raw_path=RAW_PATH):
    df = pd.read_csv(raw_path, delimiter=',', encoding='utf-8', on_bad_lines='warn')

    df.columns = (
        df.columns.str.lower()
        .str.replace('è', 'e').str.replace('é', 'e').str.replace('ê', 'e')
        .str.replace('à', 'a').str.replace('â', 'a').str.replace('ï', 'i')
        .str.replace('î', 'i').str.replace('ô', 'o').str.replace('û', 'u').str.replace('ç', 'c')
        .str.replace(' ', '_').str.replace('__', '_')
        .str.replace('(', '').str.replace(')', '').str.replace('.', '')
        .str.replace(',', '').str.replace('"', '').str.replace("'", '').str.replace('/', '_')
    )

    date_entree_col = trouver_colonne(['date', 'entree'], df)
    date_sortie_col = trouver_colonne(['date', 'sortie'], df)
    date_intervention_col = trouver_colonne(['date', 'inter'], df)
    heure_entree_salle_col = trouver_colonne(['heure', 'entree', 'calimed'], df)
    heure_sortie_salle_col = trouver_colonne(['heure', 'sortie', 'calimed'], df)
    heure_incision_col = trouver_colonne(['heure', 'incision'], df)
    type_intervention_col = trouver_colonne(['interv', 'type'], df)
    date_naissance_col = trouver_colonne(['date', 'naissance'], df)
    cim_diag_pr_col = trouver_colonne(['cim', 'diag', 'pr'], df)
    ccam_1_col = trouver_colonne(['ccam', '1'], df)

    df[date_entree_col] = pd.to_datetime(df[date_entree_col], dayfirst=True, errors='coerce')
    df[date_sortie_col] = pd.to_datetime(df[date_sortie_col], dayfirst=True, errors='coerce')
    df[date_intervention_col] = pd.to_datetime(df[date_intervention_col], dayfirst=True, errors='coerce')
    df[date_naissance_col] = pd.to_datetime(df[date_naissance_col], dayfirst=True, errors='coerce')

    for col in [heure_entree_salle_col, heure_sortie_salle_col, heure_incision_col]:
        df[col] = pd.to_datetime(df[col], format='%H:%M:%S', errors='coerce').dt.time

    df['duree_avant_operation'] = (df[date_intervention_col] - df[date_entree_col]).dt.days
    df.loc[df['duree_avant_operation'] < 0, 'duree_avant_operation'] = np.nan

    def calculer_duree_bloc(row):
        jour = row[date_intervention_col]
        if pd.isna(jour):
            return np.nan
        jour = jour.date()
        try:
            if pd.notna(row[heure_entree_salle_col]) and pd.notna(row[heure_sortie_salle_col]):
                e = datetime.combine(jour, row[heure_entree_salle_col])
                s = datetime.combine(jour, row[heure_sortie_salle_col])
                return (s - e).total_seconds() / 3600
            elif pd.notna(row[heure_incision_col]) and pd.notna(row[heure_sortie_salle_col]):
                e = datetime.combine(jour, row[heure_incision_col])
                s = datetime.combine(jour, row[heure_sortie_salle_col])
                return (s - e).total_seconds() / 3600
            return np.nan
        except Exception:
            return np.nan

    df['duree_bloc_heures'] = df.apply(calculer_duree_bloc, axis=1)
    # heures de salle à 0:00:00 = non renseignées (durée nulle) -> séjour écarté de l'entraînement
    df.loc[df['duree_bloc_heures'] <= 0, 'duree_bloc_heures'] = np.nan
    df['duree_apres_operation'] = (df[date_sortie_col] - df[date_intervention_col]).dt.days
    df.loc[df['duree_apres_operation'] < 0, 'duree_apres_operation'] = np.nan

    df['type_capacite'] = np.where(
        (df['duree_avant_operation'] == 0) & (df['duree_apres_operation'] == 0),
        'ambulatoire', 'lit_classique'
    )

    df['age_annees'] = (df[date_intervention_col] - df[date_naissance_col]).dt.days / 365.25
    df['annee'] = df[date_intervention_col].dt.year
    df['mois'] = df[date_intervention_col].dt.month
    df['jour_semaine'] = df[date_intervention_col].dt.dayofweek

    # --- DÉDUCTION DU SCORE D'URGENCE (1 à 10) ---
    def calculer_score_urgence(row):
        cim = str(row.get(cim_diag_pr_col, '')).upper().strip()
        ccam = str(row.get(ccam_1_col, '')).upper().strip()

        # 1. URGENCE TRÈS ÉLEVÉE (8 à 10) : traumatologie aiguë et plaies
        if cim.startswith(('S', 'T')):
            return 9
        if any(ccam.startswith(p) for p in ['PAGA', 'PCPA', 'NAQK', 'NDQK', 'NDPA', 'MDQK', 'MFPA', 'MGQK']):
            return 8

        # 2. SEMI-URGENT (5 à 7) : infections cutanées, abcès
        if cim.startswith(('L02', 'L03', 'K80', 'K81')):
            return 6

        # 3. AMBULATOIRE / PETITE CHIRURGIE PROGRAMMÉE (3 à 4)
        if cim.startswith(('M20', 'L60', 'G56', 'M72', 'M65', 'M70')) or any(ccam.startswith(p) for p in ['NFMA', 'NFMC', 'MJFA', 'MEMC', 'QZFA', 'QZJA', 'EJSA']):
            return 3

        # 4. CHIRURGIE LOURDE FROIDE / RÉGLÉE (1 à 2)
        if cim.startswith(('M16', 'M17', 'M48', 'M50', 'M51', 'Z47')) or any(ccam.startswith(p) for p in ['NFKA', 'NEKA', 'NEQK']):
            return 1

        return 3

    df['urgence'] = df.apply(calculer_score_urgence, axis=1)

    df = df.rename(columns={type_intervention_col: 'type_intervention'})

    keep = ['no_cas', 'type_intervention', 'cim_diag_pr', 'ccam_1', 'sexe',
            'praticien', 'anesth_type', 'anesth_loco_reg',
            'age_annees', 'annee', 'mois', 'jour_semaine',
            'duree_avant_operation', 'duree_bloc_heures', 'duree_apres_operation',
            'type_capacite', 'urgence']
    df = df[[c for c in keep if c in df.columns]].copy()

    for c in CAT_COLS:
        df[c] = df[c].astype(str).replace('nan', 'Inconnu').fillna('Inconnu')

    df = df.dropna(subset=['duree_avant_operation', 'duree_bloc_heures', 'duree_apres_operation'])

    for c in ["type_intervention", "cim_diag_pr", "ccam_1"]:
        df[c] = limiter_cardinalite(df[c], max_categories=200)

    return df


def _to_category(df_, reference=None):
    d = df_.copy()
    for c in CAT_COLS:
        if reference is not None:
            d[c] = pd.Categorical(d[c], categories=reference[c].cat.categories)
        else:
            d[c] = d[c].astype('category')
    return d


# =====================================================================
# A) VALIDATION EMPIRIQUE SUR UN VRAI JEU DE TEST
# =====================================================================
def valider_sur_jeu_de_test():
    df = charger_et_preparer()
    y_cap = df['type_capacite']

    idx_train, idx_test = train_test_split(
        df.index, test_size=0.2, random_state=RANDOM_STATE, stratify=y_cap
    )
    df_train, df_test = df.loc[idx_train], df.loc[idx_test]

    Xc_train = _to_category(df_train[CAT_COLS + NUM_COLS])
    Xc_test = _to_category(df_test[CAT_COLS + NUM_COLS], reference=Xc_train)

    clf = HistGradientBoostingClassifier(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in (CAT_COLS + NUM_COLS)],
        early_stopping=True, random_state=RANDOM_STATE)
    clf.fit(Xc_train, df_train['type_capacite'])
    cap_pred_test = clf.predict(Xc_test)

    reg_bloc = HistGradientBoostingRegressor(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in (CAT_COLS + NUM_COLS)],
        early_stopping=True, random_state=RANDOM_STATE)
    reg_bloc.fit(Xc_train, df_train['duree_bloc_heures'])
    bloc_pred_test = np.clip(reg_bloc.predict(Xc_test), 0, None)

    reg_urgence = HistGradientBoostingRegressor(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in (CAT_COLS + NUM_COLS)],
        early_stopping=True, random_state=RANDOM_STATE)
    reg_urgence.fit(Xc_train, df_train['urgence'])
    urgence_pred_test = np.clip(np.round(reg_urgence.predict(Xc_test)), 1, 10).astype(int)

    train_lit = df_train[df_train['type_capacite'] == 'lit_classique']
    Xc_train_lit = _to_category(train_lit[CAT_COLS + NUM_COLS])

    reg_avant = HistGradientBoostingRegressor(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in (CAT_COLS + NUM_COLS)],
        early_stopping=True, random_state=RANDOM_STATE)
    reg_avant.fit(Xc_train_lit, train_lit['duree_avant_operation'])

    reg_apres = HistGradientBoostingRegressor(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in (CAT_COLS + NUM_COLS)],
        early_stopping=True, random_state=RANDOM_STATE)
    reg_apres.fit(Xc_train_lit, train_lit['duree_apres_operation'])

    Xc_test_full = _to_category(df_test[CAT_COLS + NUM_COLS], reference=Xc_train)
    avant_pred_test = np.where(
        cap_pred_test == 'lit_classique',
        np.clip(reg_avant.predict(Xc_test_full), 0, None), 0.0)
    apres_pred_test = np.where(
        cap_pred_test == 'lit_classique',
        np.clip(reg_apres.predict(Xc_test_full), 0, None), 0.0)

    print("=" * 70)
    print("MÉTRIQUES GLOBALES — pipeline complet sur le jeu de test (20%, jamais vu)")
    print("=" * 70)

    acc = accuracy_score(df_test['type_capacite'], cap_pred_test)
    f1 = f1_score(df_test['type_capacite'], cap_pred_test, pos_label='lit_classique')
    print("\n[Classification type_capacite]")
    print(f"  Accuracy : {acc:.3f}   F1 (lit_classique) : {f1:.3f}")
    print("  Matrice de confusion (lignes=réel, colonnes=prédit) :")
    print("  ", confusion_matrix(df_test['type_capacite'], cap_pred_test,
                                  labels=['ambulatoire', 'lit_classique']))

    for nom, y_true, y_pred in [
        ("duree_bloc_heures", df_test['duree_bloc_heures'], bloc_pred_test),
        ("duree_avant_operation (pipeline complet)", df_test['duree_avant_operation'], avant_pred_test),
        ("duree_apres_operation (pipeline complet)", df_test['duree_apres_operation'], apres_pred_test),
        ("urgence (score 1-10)", df_test['urgence'], urgence_pred_test),
    ]:
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        r2 = r2_score(y_true, y_pred)
        print(f"\n[{nom}]")
        print(f"  MAE : {mae:.2f}   RMSE : {rmse:.2f}   R² : {r2:.3f}")

    print("\n" + "=" * 70)
    print("EXEMPLES DE CAS RÉELS (échantillon du jeu de test)")
    print("=" * 70)

    echantillon = df_test.sample(n=min(15, len(df_test)), random_state=1).index

    tableau_1 = pd.DataFrame({
        "type_intervention": df_test.loc[echantillon, "type_intervention"].str.slice(0, 22),
        "capacite_reelle": df_test.loc[echantillon, "type_capacite"],
        "capacite_predite": pd.Series(cap_pred_test, index=df_test.index).loc[echantillon],
        "bloc_h_reel": df_test.loc[echantillon, "duree_bloc_heures"].round(2),
        "bloc_h_predit": pd.Series(bloc_pred_test, index=df_test.index).loc[echantillon].round(2),
        "urg_reelle": df_test.loc[echantillon, "urgence"],
        "urg_predite": pd.Series(urgence_pred_test, index=df_test.index).loc[echantillon],
    })
    print("\n-- Capacité + durée bloc + urgence --")
    print(tableau_1.to_string(index=False))

    tableau_2 = pd.DataFrame({
        "type_intervention": df_test.loc[echantillon, "type_intervention"].str.slice(0, 22),
        "avant_j_reel": df_test.loc[echantillon, "duree_avant_operation"],
        "avant_j_predit": pd.Series(avant_pred_test, index=df_test.index).loc[echantillon].round(1),
        "apres_j_reel": df_test.loc[echantillon, "duree_apres_operation"],
        "apres_j_predit": pd.Series(apres_pred_test, index=df_test.index).loc[echantillon].round(1),
        "erreur_apres_j": np.abs(
            df_test.loc[echantillon, "duree_apres_operation"].values
            - pd.Series(apres_pred_test, index=df_test.index).loc[echantillon].values
        ).round(1),
    })
    print("\n-- Durée avant / après opération (la donnée clé pour l'occupation des lits) --")
    print(tableau_2.to_string(index=False))

    # --- Pires erreurs, sur les 3 durées + urgence séparément ---
    erreurs_bloc = pd.DataFrame({
        "type_intervention": df_test["type_intervention"],
        "bloc_h_reel": df_test["duree_bloc_heures"],
        "bloc_h_predit": bloc_pred_test,
        "erreur_abs_bloc_h": np.abs(df_test["duree_bloc_heures"].values - bloc_pred_test),
    }).sort_values("erreur_abs_bloc_h", ascending=False)

    print("\n" + "=" * 70)
    print("PIRES ERREURS — durée bloc opératoire (top 10)")
    print("=" * 70)
    print(erreurs_bloc.head(10).to_string(index=False))

    erreurs_apres = pd.DataFrame({
        "type_intervention": df_test["type_intervention"],
        "capacite_reelle": df_test["type_capacite"],
        "capacite_predite": cap_pred_test,
        "apres_j_reel": df_test["duree_apres_operation"],
        "apres_j_predit": apres_pred_test,
        "erreur_abs_apres_j": np.abs(df_test["duree_apres_operation"].values - apres_pred_test),
    }).sort_values("erreur_abs_apres_j", ascending=False)

    print("\n" + "=" * 70)
    print("PIRES ERREURS — durée APRÈS opération (top 10)  <-- la plus importante pour toi")
    print("=" * 70)
    print(erreurs_apres.head(10).to_string(index=False))

    erreurs_avant = pd.DataFrame({
        "type_intervention": df_test["type_intervention"],
        "capacite_reelle": df_test["type_capacite"],
        "capacite_predite": cap_pred_test,
        "avant_j_reel": df_test["duree_avant_operation"],
        "avant_j_predit": avant_pred_test,
        "erreur_abs_avant_j": np.abs(df_test["duree_avant_operation"].values - avant_pred_test),
    }).sort_values("erreur_abs_avant_j", ascending=False)

    print("\n" + "=" * 70)
    print("PIRES ERREURS — durée avant opération (top 10)")
    print("=" * 70)
    print(erreurs_avant.head(10).to_string(index=False))

    erreurs_urgence = pd.DataFrame({
        "type_intervention": df_test["type_intervention"],
        "urg_reelle": df_test["urgence"],
        "urg_predite": urgence_pred_test,
        "erreur_abs_urg": np.abs(df_test["urgence"].values - urgence_pred_test),
    }).sort_values("erreur_abs_urg", ascending=False)

    print("\n" + "=" * 70)
    print("PIRES ERREURS — score d'urgence (top 10)")
    print("=" * 70)
    print(erreurs_urgence.head(10).to_string(index=False))

    # --- Répartition des erreurs sur la durée après opération ---
    erreur_apres_abs = np.abs(df_test["duree_apres_operation"].values - apres_pred_test)
    print("\n" + "=" * 70)
    print("RÉPARTITION DE L'ERREUR — durée après opération (en jours)")
    print("=" * 70)
    for seuil in [0.5, 1, 2, 3]:
        pct = (erreur_apres_abs <= seuil).mean() * 100
        print(f"  Erreur ≤ {seuil} jour(s) : {pct:.1f}% des patients du jeu de test")

    # --- Répartition des erreurs sur l'urgence ---
    erreur_urg_abs = np.abs(df_test["urgence"].values - urgence_pred_test)
    print("\n" + "=" * 70)
    print("RÉPARTITION DE L'ERREUR — score d'urgence")
    print("=" * 70)
    for seuil in [0, 1, 2]:
        pct = (erreur_urg_abs <= seuil).mean() * 100
        print(f"  Écart ≤ {seuil} point(s) : {pct:.1f}% des patients du jeu de test")


# =====================================================================
# B) UTILISATION PRATIQUE : modèles de PRODUCTION sur des cas fictifs
# =====================================================================
def charger_modeles_production():
    return {
        "clf_capacite": joblib.load(MODELES_DIR / "clf_type_capacite.joblib"),
        "reg_bloc": joblib.load(MODELES_DIR / "reg_duree_bloc.joblib"),
        "reg_avant": joblib.load(MODELES_DIR / "reg_duree_avant.joblib"),
        "reg_apres": joblib.load(MODELES_DIR / "reg_duree_apres.joblib"),
        "reg_urgence": joblib.load(MODELES_DIR / "reg_urgence.joblib"),
    }


def predire_patient(patient: dict, modeles: dict) -> dict:
    X_new = pd.DataFrame([patient])[CAT_COLS + NUM_COLS]
    for c in CAT_COLS:
        X_new[c] = X_new[c].astype(str).astype('category')

    capacite = modeles["clf_capacite"].predict(X_new)[0]
    bloc = max(0.0, float(modeles["reg_bloc"].predict(X_new)[0]))
    urg = int(np.clip(round(float(modeles["reg_urgence"].predict(X_new)[0])), 1, 10))

    resultat = {
        "type_capacite_predit": capacite,
        "duree_bloc_heures_predit": round(bloc, 2),
        "urgence_predite": urg,
    }
    if capacite == "lit_classique":
        avant = max(0.0, float(modeles["reg_avant"].predict(X_new)[0]))
        apres = max(0.0, float(modeles["reg_apres"].predict(X_new)[0]))
        resultat["duree_avant_operation_jours"] = round(avant, 1)
        resultat["duree_apres_operation_jours"] = round(apres, 1)
    else:
        resultat["duree_avant_operation_jours"] = 0
        resultat["duree_apres_operation_jours"] = 0
    return resultat


def tester_cas_fictifs():
    modeles = charger_modeles_production()

    cas_pratiques = {
        "PTH chez patient âgé (attendu : lit classique, durées longues, urgence basse 1-2)": {
            "type_intervention": "Prothese Totale Hanche", "cim_diag_pr": "M16.1",
            "ccam_1": "NEKA020", "sexe": "1", "praticien": "CL",
            "anesth_type": "AG avec intubation", "anesth_loco_reg": "Inconnu",
            "age_annees": 78, "annee": 2026, "mois": 3, "jour_semaine": 1,
        },
        "Arthroscopie genou jeune patient (attendu : ambulatoire, bloc court, urgence modérée)": {
            "type_intervention": "Arthroscopie Genou", "cim_diag_pr": "S83.2",
            "ccam_1": "NFEA001", "sexe": "2", "praticien": "LZ",
            "anesth_type": "AG avec masque laryngé", "anesth_loco_reg": "Bloc coude",
            "age_annees": 24, "annee": 2026, "mois": 6, "jour_semaine": 3,
        },
        "Fracture diaphysaire fémur (attendu : lit classique, urgence haute 8-9)": {
            "type_intervention": "Osteosynthese Femur", "cim_diag_pr": "S72.3",
            "ccam_1": "NDQK001", "sexe": "1", "praticien": "Inconnu",
            "anesth_type": "AG avec intubation", "anesth_loco_reg": "Inconnu",
            "age_annees": 45, "annee": 2026, "mois": 2, "jour_semaine": 2,
        },
        "Chirurgie non vue à l'entraînement (attendu : le modèle doit quand même répondre)": {
            "type_intervention": "Intervention totalement inconnue XYZ", "cim_diag_pr": "Z99.9",
            "ccam_1": "INCONNU", "sexe": "1", "praticien": "Inconnu",
            "anesth_type": "Inconnu", "anesth_loco_reg": "Inconnu",
            "age_annees": 50, "annee": 2026, "mois": 1, "jour_semaine": 0,
        },
    }

    print("\n" + "=" * 70)
    print("CAS PRATIQUES FICTIFS — modèles de production (entraînés sur 100% des données)")
    print("=" * 70)
    for description, patient in cas_pratiques.items():
        resultat = predire_patient(patient, modeles)
        print(f"\n--- {description} ---")
        for k, v in resultat.items():
            print(f"  {k} : {v}")


if __name__ == "__main__":
    valider_sur_jeu_de_test()
    tester_cas_fictifs()