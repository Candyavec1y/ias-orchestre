"""
=====================================================================
MODÈLES PRÉDICTIFS - VERSION RAPIDE (premier résultat en quelques minutes)
=====================================================================
Un seul modèle par cible (HistGradientBoosting, natif scikit-learn :
pas d'installation externe, gère nativement les variables catégorielles
et les valeurs manquantes, entraînement très rapide même sur des
variables à forte cardinalité comme type_intervention).

Évaluation par un simple split train/test (80/20), pas de validation
croisée exhaustive : c'est volontairement "quick & dirty" pour juger
en quelques minutes si l'approche est prometteuse. Une fois validée,
utilise le script complet (modeles_prediction.py) pour comparer
plusieurs familles de modèles avec validation croisée.
=====================================================================
"""

import time
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
    accuracy_score, f1_score, classification_report,
)

RANDOM_STATE = 42
OUTPUT_DIR = Path("outputs/models_rapide")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_PATH = Path("donnees_hospitalieres.csv")

CAT_COLS = ["type_intervention", "cim_diag_pr", "ccam_1", "sexe",
            "praticien", "anesth_type", "anesth_loco_reg"]
NUM_COLS = ["age_annees", "annee", "mois", "jour_semaine"]


# =====================================================================
# Recherche de colonnes (ta version, avec garde-fou anti-ambiguïté)
# =====================================================================
def trouver_colonne(mots_cles, df, min_match=None):
    """
    min_match=None -> exige TOUS les mots-clés (comportement sûr, équivalent
    à l'ancien all()). Ne baisse min_match que si tu es certain qu'aucune
    colonne ne contient tous les mots-clés à la fois : un seuil trop bas
    (ex. 1) peut faire matcher une colonne non liée qui ne contient qu'un
    des mots-clés par hasard (ça nous a déjà fait planter/mal matcher).
    """
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


# =====================================================================
# Chargement + préparation (identique à avant, condensé)
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

        # 1. URGENCE TRÈS ÉLEVÉE (8 à 10) : fractures, traumatismes aigus, plaies, hémostase
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

        # Reste : programmation élective standard
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


def limiter_cardinalite(serie, max_categories=200):
    top = serie.value_counts().nlargest(max_categories).index
    return serie.where(serie.isin(top), other="Autre")


def _to_category(df_):
    d = df_.copy()
    for c in CAT_COLS:
        d[c] = d[c].astype('category')
    return d


def entrainer_regression_rapide(X, y, nom_cible):
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE)
    Xc_tr, Xc_te = _to_category(X_tr), _to_category(X_te)
    for c in CAT_COLS:
        Xc_te[c] = pd.Categorical(Xc_te[c], categories=Xc_tr[c].cat.categories)

    t0 = time.time()
    model = HistGradientBoostingRegressor(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in X.columns],
        early_stopping=True, random_state=RANDOM_STATE)
    model.fit(Xc_tr, y_tr)
    pred = np.clip(model.predict(Xc_te), 0, None)
    duree = time.time() - t0

    print(f"\n--- {nom_cible} (HistGradientBoosting, {duree:.1f}s) ---")
    print(f"MAE  : {mean_absolute_error(y_te, pred):.2f}")
    print(f"RMSE : {np.sqrt(mean_squared_error(y_te, pred)):.2f}")
    print(f"R²   : {r2_score(y_te, pred):.3f}")

    # Réentraînement sur 100% des données pour le modèle final sauvegardé
    Xc_full = _to_category(X)
    model_final = HistGradientBoostingRegressor(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in X.columns],
        random_state=RANDOM_STATE)
    model_final.fit(Xc_full, y)
    return model_final


def entrainer_classification_rapide(X, y):
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y)
    Xc_tr, Xc_te = _to_category(X_tr), _to_category(X_te)
    for c in CAT_COLS:
        Xc_te[c] = pd.Categorical(Xc_te[c], categories=Xc_tr[c].cat.categories)

    t0 = time.time()
    model = HistGradientBoostingClassifier(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in X.columns],
        early_stopping=True, random_state=RANDOM_STATE)
    model.fit(Xc_tr, y_tr)
    pred = model.predict(Xc_te)
    duree = time.time() - t0

    print(f"\n--- type_capacite (HistGradientBoosting, {duree:.1f}s) ---")
    print(f"Accuracy : {accuracy_score(y_te, pred):.3f}")
    print(f"F1 (lit_classique) : {f1_score(y_te, pred, pos_label='lit_classique'):.3f}")
    print(classification_report(y_te, pred))

    Xc_full = _to_category(X)
    model_final = HistGradientBoostingClassifier(
        max_depth=6, learning_rate=0.08, max_iter=200,
        categorical_features=[c in CAT_COLS for c in X.columns],
        random_state=RANDOM_STATE)
    model_final.fit(Xc_full, y)
    return model_final


if __name__ == "__main__":
    t_debut = time.time()
    print("Chargement et préparation des données...")
    df = charger_et_preparer()
    print(f"-> {len(df)} séjours utilisables.\n")

    X_all = df[CAT_COLS + NUM_COLS]

    clf_capacite = entrainer_classification_rapide(X_all, df['type_capacite'])
    reg_bloc = entrainer_regression_rapide(X_all, df['duree_bloc_heures'], "duree_bloc_heures")

    # --- MODÈLE D'URGENCE ---
    reg_urgence = entrainer_regression_rapide(X_all, df['urgence'], "degre_urgence")

    df_lit = df[df['type_capacite'] == 'lit_classique']
    X_lit = df_lit[CAT_COLS + NUM_COLS]
    reg_avant = entrainer_regression_rapide(X_lit, df_lit['duree_avant_operation'], "duree_avant_operation")
    reg_apres = entrainer_regression_rapide(X_lit, df_lit['duree_apres_operation'], "duree_apres_operation")

    joblib.dump(clf_capacite, OUTPUT_DIR / "clf_type_capacite.joblib")
    joblib.dump(reg_bloc, OUTPUT_DIR / "reg_duree_bloc.joblib")
    joblib.dump(reg_avant, OUTPUT_DIR / "reg_duree_avant.joblib")
    joblib.dump(reg_apres, OUTPUT_DIR / "reg_duree_apres.joblib")
    joblib.dump(reg_urgence, OUTPUT_DIR / "reg_urgence.joblib")

    print(f"\n✅ Terminé en {time.time() - t_debut:.1f} secondes. Modèles sauvegardés dans {OUTPUT_DIR}")