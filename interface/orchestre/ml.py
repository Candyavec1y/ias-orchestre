# -*- coding: utf-8 -*-
"""
Prédictions de consultation (machine_learning/).

Réutilise les modèles de PRODUCTION du dépôt (outputs/models_rapide/*.joblib, HistGradientBoosting
entraînés par modele_prediction_rapide.py) et la fonction predire_patient() de utilisation_modèle.py.
La qualité affichée à l'utilisateur provient de la validation 80 % / 20 % (même protocole que
utilisation_modèle.valider_sur_jeu_de_test) ; seules des MÉTRIQUES AGRÉGÉES sont conservées,
jamais de ligne individuelle du jeu de données historique.
"""
from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Optional

from . import chemins

warnings.filterwarnings("ignore")

CAT_COLS = ["type_intervention", "cim_diag_pr", "ccam_1", "sexe", "praticien", "anesth_type", "anesth_loco_reg"]
NUM_COLS = ["age_annees", "annee", "mois", "jour_semaine"]
FICHIERS = {"clf_capacite": "clf_type_capacite.joblib", "reg_bloc": "reg_duree_bloc.joblib",
            "reg_avant": "reg_duree_avant.joblib", "reg_apres": "reg_duree_apres.joblib",
            "reg_urgence": "reg_urgence.joblib"}
CACHE_METRIQUES = chemins.DOSSIER_DONNEES / "metriques_ml.json"

LIBELLES_SEXE = {"1": "Homme (1)", "2": "Femme (2)"}         # convention PMSI du fichier source
INCONNU = "Inconnu"

RE_CIM = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")
RE_CCAM = re.compile(r"^[A-Z]{4}[0-9]{3}$")


def _utilisation():
    return chemins.importer_fichier("utilisation_modele",
                                    chemins.RACINE / "machine_learning" / "utilisation_modèle.py")


@lru_cache(maxsize=1)
def modeles() -> dict:
    import joblib
    return {k: joblib.load(chemins.DOSSIER_MODELES_ML / f) for k, f in FICHIERS.items()}


@lru_cache(maxsize=1)
def vocabulaires() -> dict[str, list[str]]:
    """Modalités vues à l'entraînement (encodeur ordinal interne du modèle de capacité)."""
    enc = modeles()["clf_capacite"]._preprocessor.named_transformers_["encoder"]
    voc = {}
    for col, cats in zip(CAT_COLS, enc.categories_):
        voc[col] = sorted(str(c) for c in cats if str(c) not in ("nan", "Autre", INCONNU))
    return voc


# ---------------------------------------------------------------- codes
def normaliser_cim(code: str) -> str:
    c = (code or "").strip().upper().replace(" ", "")
    if len(c) > 3 and "." not in c:
        c = c[:3] + "." + c[3:]
    return c


def normaliser_ccam(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def verifier_codes(cim: str, ccam: str) -> list[str]:
    erreurs = []
    if not RE_CIM.match(normaliser_cim(cim)):
        erreurs.append(f"CIM-10 « {cim} » : format attendu, ex. M17.1")
    if ccam and not RE_CCAM.match(normaliser_ccam(ccam)):
        erreurs.append(f"CCAM « {ccam} » : format attendu, ex. NFKA008 (4 lettres + 3 chiffres)")
    return erreurs


# ---------------------------------------------------------------- prédiction
def priorite_depuis_score(score: int) -> int:
    """Score d'urgence 1-10 du modèle -> priorité clinique 1-4 des structures communes."""
    return 1 if score <= 2 else 2 if score <= 4 else 3 if score <= 7 else 4


LIBELLES_PRIORITE = {1: "1 — faible (chirurgie réglée)", 2: "2 — standard", 3: "3 — semi-urgent",
                     4: "4 — urgent"}


@dataclass
class Prediction:
    ambulatoire: bool
    proba_ambulatoire: float
    duree_bloc_min: int
    nuits_pre_op: int
    nuits_post_op: int
    score_urgence: int
    priorite: int
    entrees: dict
    hors_vocabulaire: list[str] = field(default_factory=list)   # modalités jamais vues -> fiabilité réduite

    def resume(self) -> dict:
        return {"ambulatoire": self.ambulatoire, "proba_ambulatoire": round(self.proba_ambulatoire, 3),
                "duree_bloc_min": self.duree_bloc_min, "nuits_pre_op": self.nuits_pre_op,
                "nuits_post_op": self.nuits_post_op, "score_urgence": self.score_urgence,
                "priorite": self.priorite, "hors_vocabulaire": self.hors_vocabulaire}


def entrees_modele(*, type_intervention: str, cim_diag_pr: str, ccam_1: str, sexe: str, praticien: str,
                   anesth_type: str, anesth_loco_reg: str, age_annees: float, date_intervention: date) -> dict:
    return {
        "type_intervention": type_intervention.strip() or INCONNU,
        "cim_diag_pr": normaliser_cim(cim_diag_pr) or INCONNU,
        "ccam_1": normaliser_ccam(ccam_1) or INCONNU,
        "sexe": str(sexe),
        "praticien": praticien or INCONNU,
        "anesth_type": anesth_type or INCONNU,
        "anesth_loco_reg": anesth_loco_reg or INCONNU,
        "age_annees": float(age_annees),
        "annee": date_intervention.year,
        "mois": date_intervention.month,
        "jour_semaine": date_intervention.weekday(),
    }


def predire(entrees: dict) -> Prediction:
    import pandas as pd
    m = modeles()
    brut = _utilisation().predire_patient(entrees, m)          # fonction du dépôt
    X = pd.DataFrame([entrees])[CAT_COLS + NUM_COLS]
    for c in CAT_COLS:
        X[c] = X[c].astype(str).astype("category")
    clf = m["clf_capacite"]
    proba = float(clf.predict_proba(X)[0][list(clf.classes_).index("ambulatoire")])
    voc = vocabulaires()
    hors = [c for c in CAT_COLS if entrees[c] != INCONNU and entrees[c] not in voc[c]]
    amb = brut["type_capacite_predit"] == "ambulatoire"
    score = int(brut["urgence_predite"])
    return Prediction(
        ambulatoire=amb, proba_ambulatoire=proba,
        duree_bloc_min=max(15, int(round(brut["duree_bloc_heures_predit"] * 60 / 5) * 5)),
        nuits_pre_op=0 if amb else int(round(brut["duree_avant_operation_jours"])),
        nuits_post_op=0 if amb else max(1, int(round(brut["duree_apres_operation_jours"]))),
        score_urgence=score, priorite=priorite_depuis_score(score), entrees=dict(entrees), hors_vocabulaire=hors)


# ---------------------------------------------------------------- validation 80/20
def metriques(recalculer: bool = False) -> Optional[dict]:
    """Métriques sur les 20 % de test (jamais vus). Calculées une fois puis mises en cache (agrégats)."""
    if CACHE_METRIQUES.exists() and not recalculer:
        return json.loads(CACHE_METRIQUES.read_text(encoding="utf-8"))
    if not chemins.CSV_HISTORIQUE.exists():
        return None
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split

    U = _utilisation()
    df = U.charger_et_preparer(str(chemins.CSV_HISTORIQUE))
    i_tr, i_te = train_test_split(df.index, test_size=0.2, random_state=42, stratify=df["type_capacite"])
    tr, te = df.loc[i_tr], df.loc[i_te]
    Xtr = U._to_category(tr[CAT_COLS + NUM_COLS])
    Xte = U._to_category(te[CAT_COLS + NUM_COLS], reference=Xtr)
    cat = [c in CAT_COLS for c in CAT_COLS + NUM_COLS]
    hp = dict(max_depth=6, learning_rate=0.08, max_iter=200, categorical_features=cat, early_stopping=True,
              random_state=42)

    clf = HistGradientBoostingClassifier(**hp).fit(Xtr, tr["type_capacite"])
    cap = clf.predict(Xte)

    def reg(Xa, y):
        return HistGradientBoostingRegressor(**hp).fit(Xa, y)

    bloc = np.clip(reg(Xtr, tr["duree_bloc_heures"]).predict(Xte), 0, None)
    urg = np.clip(np.round(reg(Xtr, tr["urgence"]).predict(Xte)), 1, 10)
    lit = tr[tr["type_capacite"] == "lit_classique"]
    Xlit = U._to_category(lit[CAT_COLS + NUM_COLS])
    avant = np.where(cap == "lit_classique", np.clip(reg(Xlit, lit["duree_avant_operation"]).predict(Xte), 0, None), 0)
    apres = np.where(cap == "lit_classique", np.clip(reg(Xlit, lit["duree_apres_operation"]).predict(Xte), 0, None), 0)

    def r(y, p):
        return {"mae": float(mean_absolute_error(y, p)), "r2": float(r2_score(y, p))}

    err_apres = np.abs(te["duree_apres_operation"].values - apres)
    res = {
        "n_total": int(len(df)), "n_train": int(len(tr)), "n_test": int(len(te)),
        "capacite": {"accuracy": float(accuracy_score(te["type_capacite"], cap)),
                     "f1_lit": float(f1_score(te["type_capacite"], cap, pos_label="lit_classique")),
                     "confusion": confusion_matrix(te["type_capacite"], cap,
                                                   labels=["ambulatoire", "lit_classique"]).tolist()},
        "duree_bloc_heures": r(te["duree_bloc_heures"], bloc),
        "nuits_avant": r(te["duree_avant_operation"], avant),
        "nuits_apres": r(te["duree_apres_operation"], apres),
        "urgence": r(te["urgence"], urg) | {"exact_pct": float((np.abs(te["urgence"].values - urg) == 0).mean() * 100)},
        "apres_erreur_le_1j_pct": float((err_apres <= 1).mean() * 100),
        "apres_erreur_le_2j_pct": float((err_apres <= 2).mean() * 100),
    }
    CACHE_METRIQUES.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
