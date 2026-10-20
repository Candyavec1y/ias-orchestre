# -*- coding: utf-8 -*-
"""
Outils partagés par les scripts de campagne de resultats_rapport/ (aucun code du projet n'est modifié : les modules
du dépôt sont seulement importés, comme le fait l'interface via orchestre/chemins.py).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SORTIE = RACINE / "resultats_rapport"
FIGURES = SORTIE / "figures"
AGREGEES = SORTIE / "donnees_agregees"
for _d in (FIGURES, AGREGEES):
    _d.mkdir(parents=True, exist_ok=True)

for _nom in reversed(["commun", "planning_vacations", "metaheuristiques", "sma", "machine_learning"]):
    _p = str(RACINE / _nom)
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
sys.path.insert(0, str(RACINE / "interface"))

import structures_communes  # noqa: E402,F401  (version commune chargée en premier, comme l'interface)

# Couleur unique par méthode dans toutes les figures (lisible en niveaux de gris : marqueurs distincts)
COULEURS = {"glouton": "#7f7f7f", "premier créneau": "#bcbd22", "RS seul": "#1f77b4", "TABOU seul": "#ff7f0e", "AGS seul": "#2ca02c",
            "memetique": "#d62728", "AGS>RS>TABOU": "#9467bd", "RS>AGS>TABOU": "#8c564b"}
MARQUEURS = {"glouton": "o", "premier créneau": "*", "RS seul": "s", "TABOU seul": "^", "AGS seul": "v", "memetique": "D",
             "AGS>RS>TABOU": "P", "RS>AGS>TABOU": "X"}
METHODES = ["RS seul", "TABOU seul", "AGS seul", "memetique", "AGS>RS>TABOU", "RS>AGS>TABOU"]


def commit_git() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=RACINE, capture_output=True, text=True).stdout.strip()


def sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def ecrire_csv(chemin: Path, lignes: list[dict]) -> None:
    """CSV sans arrondi (valeurs brutes) ; colonnes = union ordonnée des clés."""
    cols: list[str] = []
    for l_ in lignes:
        cols += [k for k in l_ if k not in cols]
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(lignes)


def lire_csv(chemin: Path) -> list[dict]:
    with open(chemin, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ecrire_json(chemin: Path, donnees) -> None:
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def resume_stat(valeurs: list[float]) -> dict:
    """Moyenne, écart-type, médiane, min, max et IC95 % de la moyenne (t de Student) ; n = nombre de valeurs."""
    v = [x for x in valeurs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(v)
    if n == 0:
        return {"n": 0}
    m = statistics.fmean(v)
    sd = statistics.stdev(v) if n > 1 else 0.0
    from scipy import stats
    demi = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n) if n > 1 else float("nan")
    return {"n": n, "moyenne": m, "ecart_type": sd, "mediane": statistics.median(v), "min": min(v), "max": max(v),
            "ic95_bas": m - demi if n > 1 else float("nan"), "ic95_haut": m + demi if n > 1 else float("nan")}


def fr(x, decimales: int = 1) -> str:
    """Nombre au format français (virgule décimale, espace fine pour les milliers) pour LaTeX / Markdown."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:,.{decimales}f}".replace(",", " ").replace(".", ",")
    return s


def sauver_figure(fig, nom: str) -> list[str]:
    fichiers = []
    for ext in ("png",):                     # PNG 300 dpi uniquement
        p = FIGURES / f"{nom}.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        fichiers.append(str(p.relative_to(SORTIE)))
    return fichiers


MANIFESTE = SORTIE / "manifest.json"


def enregistrer_manifeste(produit: str, sources: list[str], script: str, statut: str = "MESURÉ", note: str = ""):
    """Relie chaque figure / tableau aux fichiers agrégés et au script qui l'ont produit."""
    m = json.loads(MANIFESTE.read_text(encoding="utf-8")) if MANIFESTE.exists() else {"commit": commit_git(),
                                                                                       "produits": {}}
    m["produits"][produit] = {"sources": sources, "script": script, "statut": statut, "note": note}
    ecrire_json(MANIFESTE, m)
