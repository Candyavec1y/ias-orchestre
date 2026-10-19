# -*- coding: utf-8 -*-
"""
machine_learning/preparation.py — PRÉPARATION DES DONNÉES ET ÉVALUATION, communes à tout le machine learning
=============================================================================================================

Utilisé par modele_prediction_rapide.py (entraînement), utilisation_modele.py (validation détaillée, cas fictifs)
et interface/orchestre/ml.py (prédictions et qualité affichées dans l'onglet Consultation) : une seule préparation,
une seule règle d'urgence, une seule séparation entraînement / test, une seule évaluation.

    charger_et_preparer()   lecture de donnees_hospitalieres.csv -> une ligne par séjour, cibles calculées
    regle_urgence(cim, ccam) score d'urgence 1-10 par RÈGLE (D8)
    separer(df)             split UNIQUE 80 / 20 stratifié sur le mode de prise en charge, pour toutes les cibles
    evaluer(df)             métriques sur le jeu de test (tailles réelles, R², MAE, RMSE, accuracy, F1, confusion)

Les modèles pré- et postopératoires n'apprennent et ne sont évalués que sur les HOSPITALISÉS du même split.
"""
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, mean_absolute_error, mean_squared_error,
                             r2_score)
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")

_COMMUN = str(Path(__file__).resolve().parents[1] / "commun")
if _COMMUN not in sys.path:
    sys.path.insert(0, _COMMUN)
from parametres import GRAINE_ML  # noqa: E402

DOSSIER = Path(__file__).resolve().parent
CSV_DONNEES = DOSSIER / "donnees_hospitalieres.csv"
DOSSIER_MODELES = DOSSIER / "outputs" / "models_rapide"

CAT_COLS = ["type_intervention", "cim_diag_pr", "ccam_1", "sexe",
            "praticien", "anesth_type", "anesth_loco_reg"]
NUM_COLS = ["age_annees", "annee", "mois", "jour_semaine"]
CIBLE_CAPACITE = "type_capacite"
HOSPITALISE = "lit_classique"
TAILLE_TEST = 0.2
HYPERPARAMETRES = dict(max_depth=6, learning_rate=0.08, max_iter=200)
VERSION_EVALUATION = 2           # change -> le cache des métriques de l'interface est recalculé


# =====================================================================
# Recherche de colonnes
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
# Chargement + préparation
# =====================================================================
def regle_urgence(cim, ccam) -> int:
    """SCORE D'URGENCE 1-10 : RÈGLE de calcul du projet à partir du code CIM-10 principal et du premier acte CCAM
    (fonction UNIQUE : préparation des données, interface, priorité proposée au médecin). Ce n'est NI une donnée
    observée NI un score d'urgence validé cliniquement ; le médecin valide ou corrige la priorité qui en découle."""
    cim = str(cim if cim is not None else '').upper().strip()
    ccam = str(ccam if ccam is not None else '').upper().strip()

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


def charger_et_preparer(raw_path=CSV_DONNEES):
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

    # --- SCORE D'URGENCE : RÈGLE du projet (regle_urgence), pas une donnée observée (D8) ---
    df['urgence'] = [regle_urgence(c, a) for c, a in zip(df[cim_diag_pr_col], df[ccam_1_col])]

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


# =====================================================================
# Modèles, séparation, évaluation
# =====================================================================
def vers_categories(df_, reference=None):
    """Colonnes catégorielles en `category` ; `reference` : mêmes catégories que le jeu d'entraînement."""
    d = df_.copy()
    for c in CAT_COLS:
        d[c] = (pd.Categorical(d[c], categories=reference[c].cat.categories) if reference is not None
                else d[c].astype('category'))
    return d


def modele(classification: bool, early_stopping="auto", graine: int = GRAINE_ML):
    """HistGradientBoosting avec les hyperparamètres du projet."""
    classe = HistGradientBoostingClassifier if classification else HistGradientBoostingRegressor
    return classe(**HYPERPARAMETRES, categorical_features=[c in CAT_COLS for c in CAT_COLS + NUM_COLS],
                  early_stopping=early_stopping, random_state=graine)


def separer(df, graine: int = GRAINE_ML):
    """Split UNIQUE 80 / 20, stratifié sur le mode de prise en charge, utilisé pour TOUTES les cibles."""
    i_tr, i_te = train_test_split(df.index, test_size=TAILLE_TEST, random_state=graine, stratify=df[CIBLE_CAPACITE])
    return df.loc[i_tr], df.loc[i_te]


def _regression(y, p) -> dict:
    return {"n_test": int(len(y)), "mae": float(mean_absolute_error(y, p)),
            "rmse": float(np.sqrt(mean_squared_error(y, p))), "r2": float(r2_score(y, p))}


def evaluer(df, details: bool = False, graine: int = GRAINE_ML):
    """Métriques sur le jeu de test (jamais vu à l'entraînement). `details` : renvoie aussi les prédictions du test."""
    tr, te = separer(df, graine)
    xtr = vers_categories(tr[CAT_COLS + NUM_COLS])
    xte = vers_categories(te[CAT_COLS + NUM_COLS], reference=xtr)
    cap = modele(True, True, graine).fit(xtr, tr[CIBLE_CAPACITE]).predict(xte)
    bloc = np.clip(modele(False, True, graine).fit(xtr, tr["duree_bloc_heures"]).predict(xte), 0, None)
    lit_tr, lit_te = tr[tr[CIBLE_CAPACITE] == HOSPITALISE], te[te[CIBLE_CAPACITE] == HOSPITALISE]
    xlit_tr = vers_categories(lit_tr[CAT_COLS + NUM_COLS])
    xlit_te = vers_categories(lit_te[CAT_COLS + NUM_COLS], reference=xlit_tr)
    avant = np.clip(modele(False, True, graine).fit(xlit_tr, lit_tr["duree_avant_operation"]).predict(xlit_te), 0, None)
    apres = np.clip(modele(False, True, graine).fit(xlit_tr, lit_tr["duree_apres_operation"]).predict(xlit_te), 0, None)
    classes = sorted(df[CIBLE_CAPACITE].unique())
    err_apres = np.abs(lit_te["duree_apres_operation"].values - apres)
    res = {
        "version": VERSION_EVALUATION, "n_total": int(len(df)), "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_test_hospitalises": int(len(lit_te)),
        "capacite": {"n_test": int(len(te)), "accuracy": float(accuracy_score(te[CIBLE_CAPACITE], cap)),
                     "f1_par_classe": dict(zip(classes, map(float, f1_score(te[CIBLE_CAPACITE], cap, labels=classes,
                                                                            average=None)))),
                     "classes": classes,
                     "confusion": confusion_matrix(te[CIBLE_CAPACITE], cap, labels=classes).tolist()},
        "duree_bloc_heures": _regression(te["duree_bloc_heures"], bloc),
        "nuits_avant": _regression(lit_te["duree_avant_operation"], avant),
        "nuits_apres": _regression(lit_te["duree_apres_operation"], apres),
        "apres_erreur_le_1j_pct": float((err_apres <= 1).mean() * 100),
        "apres_erreur_le_2j_pct": float((err_apres <= 2).mean() * 100),
        "calcule_le": datetime.now().isoformat(timespec="seconds"),
    }
    if not details:
        return res
    pred = te.assign(capacite_predite=cap, bloc_h_predit=bloc)
    pred_lit = lit_te.assign(avant_j_predit=avant, apres_j_predit=apres)
    return res, pred, pred_lit


def afficher_metriques(m: dict) -> None:
    print(f"Jeu de test : {m['n_test']} séjours (dont {m['n_test_hospitalises']} hospitalisés) sur {m['n_total']}")
    c = m["capacite"]
    print(f"\n[Prise en charge] n = {c['n_test']} | accuracy {c['accuracy']:.3f} | F1 "
          + ", ".join(f"{k} {v:.3f}" for k, v in c["f1_par_classe"].items()))
    print(f"  matrice de confusion (lignes = réel, colonnes = prédit, ordre {c['classes']}) : {c['confusion']}")
    for cle, nom in (("duree_bloc_heures", "Durée au bloc (h)"), ("nuits_avant", "Nuits avant (hospitalisés)"),
                     ("nuits_apres", "Nuits après (hospitalisés)")):
        r = m[cle]
        print(f"[{nom}] n = {r['n_test']} | MAE {r['mae']:.3f} | RMSE {r['rmse']:.3f} | R² {r['r2']:.3f}")
    print(f"Nuits après à ±1 / ±2 nuit(s) : {m['apres_erreur_le_1j_pct']:.1f} % / {m['apres_erreur_le_2j_pct']:.1f} %")
