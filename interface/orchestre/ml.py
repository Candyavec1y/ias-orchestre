# -*- coding: utf-8 -*-
"""
Prédictions de consultation (machine_learning/).

Réutilise les modèles de PRODUCTION du dépôt (outputs/models_rapide/*.joblib, HistGradientBoosting entraînés par
modele_prediction_rapide.py), la fonction predire_patient() de utilisation_modele.py et la préparation commune
(machine_learning/preparation.py). Le score d'urgence n'est pas prédit : il est calculé par la RÈGLE du projet
(preparation.regle_urgence) ; ce n'est pas un score validé cliniquement et le médecin valide ou corrige la
priorité qui en découle. La qualité affichée provient de l'évaluation commune (split unique 80 / 20,
preparation.evaluer) ; seules des MÉTRIQUES AGRÉGÉES sont conservées, jamais de ligne individuelle.
"""
from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import chemins

warnings.filterwarnings("ignore")

import preparation as PREP  # noqa: E402  (machine_learning/ est dans sys.path, voir chemins)

CAT_COLS, NUM_COLS = PREP.CAT_COLS, PREP.NUM_COLS
CACHE_METRIQUES = chemins.DOSSIER_DONNEES / "metriques_ml.json"

LIBELLES_SEXE = {"1": "Homme (1)", "2": "Femme (2)"}         # convention PMSI du fichier source
INCONNU = "Inconnu"

RE_CIM = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")
RE_CCAM = re.compile(r"^[A-Z]{4}[0-9]{3}$")


def _utilisation():
    return chemins.module("utilisation_modele")


@lru_cache(maxsize=1)
def modeles() -> dict:
    return _utilisation().charger_modeles_production()


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


@lru_cache(maxsize=1)
def libelles() -> dict:
    """Libellés officiels des codes connus du modèle : CIM-10 FR (ATIH, 2025) et CCAM V84 (Assurance Maladie)."""
    return json.loads(Path(__file__).with_name("libelles_codes.json").read_text(encoding="utf-8"))


def avec_libelle(code: str, nomenclature: str) -> str:
    """« M17.1 — Autres gonarthroses primaires » ; `nomenclature` vaut "cim" ou "ccam"."""
    lib = libelles()[nomenclature].get(code)
    return f"{code} — {lib}" if lib else code


# ---------------------------------------------------------------- prédiction
def priorite_depuis_score(score: int) -> int:
    """Score d'urgence 1-10 (règle du projet) -> priorité 1-4 proposée au médecin (qui la valide ou la corrige)."""
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
    score = int(brut["score_urgence"])                       # règle, pas un modèle (D8)
    return Prediction(
        ambulatoire=amb, proba_ambulatoire=proba,
        duree_bloc_min=max(15, int(round(brut["duree_bloc_heures_predit"] * 60 / 5) * 5)),
        nuits_pre_op=0 if amb else int(round(brut["duree_avant_operation_jours"])),
        nuits_post_op=0 if amb else max(1, int(round(brut["duree_apres_operation_jours"]))),
        score_urgence=score, priorite=priorite_depuis_score(score), entrees=dict(entrees), hors_vocabulaire=hors)


# ---------------------------------------------------------------- validation 80/20
def metriques(recalculer: bool = False) -> Optional[dict]:
    """Métriques du jeu de test (évaluation commune preparation.evaluer). Calculées une fois puis mises en cache
    (agrégats seulement) ; recalculées si le protocole d'évaluation a changé."""
    if CACHE_METRIQUES.exists() and not recalculer:
        m = json.loads(CACHE_METRIQUES.read_text(encoding="utf-8"))
        if m.get("version") == PREP.VERSION_EVALUATION:
            return m
    if not chemins.CSV_HISTORIQUE.exists():
        return None
    m = PREP.evaluer(PREP.charger_et_preparer(chemins.CSV_HISTORIQUE))
    CACHE_METRIQUES.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m
