# -*- coding: utf-8 -*-
"""
metaheuristiques/sensibilite_poids.py — Sensibilité des poids de la fonction score N2
=====================================================================================

Reprend l'étude de calibrage des poids (anciens commun/calibrer_coefficients.py et commun/calcul_coeff) en corrigeant
ses incohérences :
  * les poids varient ENSEMBLE (tirage aléatoire log-uniforme, facteur entre 1/FACTEUR_MAX et FACTEUR_MAX sur chaque
    poids), et non un par un ; le jeu actuel est toujours évalué ;
  * un jeu de poids est VIABLE si la solution proposée est faisable pour le VALIDATEUR du projet (commun/validation.py,
    tolérance TOLERANCE_DEPASSEMENT_VACATION_MIN comprise) : plus de critère propre de 60 minutes de dépassement ;
  * les instances sont la cohorte de RÉFÉRENCE des campagnes (planning v28, 4 semaines + report, capacités du site
    30 / 3 / 20, cohorte 43) à 100 % et 85 % de la capacité utile — pas une instance à capacités réduites ;
  * les poids « lit » et « place » ne sont PAS calibrés : lits et places sont des contraintes dures du validateur, et
    le coût d'un lit en trop est partagé avec le SMA (COUT_LIT_EN_TROP = 5 000, « échelle commune ») ; l'étude vérifie
    seulement qu'aucune solution proposée ne déborde avec cette valeur ;
  * pas de valeur « recommandée » au bord de la grille : on publie les jeux NON DOMINÉS (moins de patients reportés,
    moins de patients prioritaires reportés, meilleure occupation du bloc) et, pour chaque poids, la plage des
    facteurs qu'ils contiennent ; une plage qui touche le bord testé est signalée comme ouverte (« ≤ » ou « ≥ ») ;
  * le jeu actuel est jugé par dominance NETTE (au moins TOL_REPORTS patients reportés en moins ET TOL_OCC points
    d'occupation en plus, sans plus de prioritaires reportés), sur la moyenne des graines.
Méthode d'optimisation : RS seul de metaheuristiques/hybridation.py (solution proposée = meilleure faisable
rencontrée), même départ et même budget pour tous les jeux.

    python metaheuristiques/sensibilite_poids.py                       # 30 tirages, 2 graines, 5 s : ≈ 3 min
    python metaheuristiques/sensibilite_poids.py --tirages 60 --budget 10 --graines 3
Sorties (resultats_rapport/sensibilite_poids/) : essais.csv, jeux.csv, sensibilite.json, compromis.png, plages.png
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from functools import lru_cache
from pathlib import Path

_ICI = Path(__file__).resolve().parent
for _d in (_ICI.parent / "commun", _ICI, _ICI.parent / "planning_vacations", _ICI.parent / "sma"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import hybridation as H  # noqa: E402
from parametres import COUT_LIT_EN_TROP, LUNDI_REFERENCE  # noqa: E402
from sorties import SuiviExecution  # noqa: E402
from structures_communes import POIDS_N2, PoidsNiveau2, SolutionPatients, evaluer_niveau2  # noqa: E402
from validation import valider_niveau2  # noqa: E402

# poids calibrés (nom, libellé, valeur actuelle) ; « report » est la pénalité par semaine de report (x priorité)
POIDS = [("non_place", "patient non placé", POIDS_N2.non_place),
         ("depassement_vac", "minute de dépassement", POIDS_N2.depassement_vac),
         ("bloc_inoccupe", "minute de bloc inoccupé", POIDS_N2.bloc_inoccupe),
         ("report", "semaine de report (x priorité)", H.PENALITE_SEMAINE_REPORT),
         ("var_lits", "variance des lits", POIDS_N2.var_lits),
         ("var_places", "variance des places", POIDS_N2.var_places)]
FIXES = {"lit": COUT_LIT_EN_TROP, "place": POIDS_N2.place}          # contraintes dures, échelle commune avec le SMA
INSTANCES = {"reference_100": 0.90, "charge_85": 0.765}             # charge du générateur (cohorte 43)
FACTEUR_MAX = 10.0
TOL_REPORTS, TOL_OCC = 2.0, 3.0
SORTIE = _ICI.parent / "resultats_rapport" / "sensibilite_poids"


@lru_cache(maxsize=4)
def instance(nom: str):
    return H.etendre_horizon(H.instance_v28(LUNDI_REFERENCE, 4, graine=43, charge=INSTANCES[nom]),
                             H.NB_SEMAINES_REPORT)


class _Etat(H.EtatAvecReport):
    def __init__(self, inst, aff, poids, report):
        super().__init__(inst, aff, penalite_semaine=report)
        self.poids = poids                      # les scores sont calculés à la demande : poids testés


class _Probleme(H.ProblemeHybrideN2):
    def __init__(self, inst, poids, report):
        super().__init__(inst, H.Journal(SuiviExecution(pas_enregistrement=10 ** 9)))
        self.poids_test, self.report = poids, report

    def etat(self, ind):
        return _Etat(self.inst, dict(zip(self.pids, ind)), self.poids_test, self.report)


def essai(args) -> dict:
    nom, jeu, facteurs, graine, budget = args
    inst = instance(nom)
    valeurs = {n: v * facteurs[n] for n, _, v in POIDS}
    report = valeurs.pop("report")
    pb = _Probleme(inst, PoidsNiveau2(**valeurs, **FIXES), report)
    rng = random.Random(graine)
    with contextlib.redirect_stdout(io.StringIO()):
        depart = pb.depuis_solution(pb.solution_initiale(rng))
        ind, _ = H.RechercheLocaleMixte(2, pb, H.ParametresRechercheLocale()).rs(depart, rng, duree=budget)
        ind = pb.solution_finale(ind)
    aff = dict(zip(pb.pids, ind))
    sol = SolutionPatients(aff)
    val = valider_niveau2(inst, sol)
    ev = evaluer_niveau2(inst, sol)                    # indicateurs bruts (indépendants des poids testés)
    V = inst.vacations
    rep = [p for p, v in aff.items() if v is not None and V[v].supplementaire]
    delais = [(V[v].jour - (inst.patients[p].date_min or LUNDI_REFERENCE)).days for p, v in aff.items() if v is not None]
    return {"instance": nom, "jeu": jeu, "graine": graine, **{f"f_{k}": v for k, v in facteurs.items()},
            "viable": val.faisable, "violations": json.dumps(val.par_type(), ensure_ascii=False),
            "reportes": len(rep), "prio_reportes": sum(inst.patients[p].priorite >= 3 for p in rep),
            "occupation_pct": ev.taux_occupation_bloc_pct, "delai_moyen_j": statistics.fmean(delais) if delais else None,
            "lits_trop": ev.depassement_lits, "places_trop": ev.depassement_places,
            "depassement_min": ev.depassement_bloc_minutes}


def domine(a: dict, b: dict, net: bool = False) -> bool:
    """a domine b (moyennes) : pas pire sur les 3 critères et meilleur sur au moins un ; `net` : nettement."""
    if net:
        return (a["reportes"] <= b["reportes"] - TOL_REPORTS and a["occupation_pct"] >= b["occupation_pct"] + TOL_OCC
                and a["prio_reportes"] <= b["prio_reportes"])
    pas_pire = (a["reportes"] <= b["reportes"] and a["prio_reportes"] <= b["prio_reportes"]
                and a["occupation_pct"] >= b["occupation_pct"])
    mieux = (a["reportes"] < b["reportes"] or a["prio_reportes"] < b["prio_reportes"]
             or a["occupation_pct"] > b["occupation_pct"])
    return pas_pire and mieux


def analyser(essais: list[dict], tirages: dict) -> tuple[list[dict], dict]:
    """Moyenne par (jeu, instance) puis par jeu (toutes instances) ; viable = faisable pour TOUTES les exécutions."""
    jeux = []
    for jeu, fac in tirages.items():
        ls = [e for e in essais if e["jeu"] == jeu]
        j = {"jeu": jeu, **{f"f_{k}": v for k, v in fac.items()}, "viable": all(e["viable"] for e in ls),
             "lits_ou_places_en_trop": sum(e["lits_trop"] + e["places_trop"] for e in ls)}
        for c in ("reportes", "prio_reportes", "occupation_pct", "delai_moyen_j", "depassement_min"):
            j[c] = statistics.fmean(e[c] for e in ls)
        jeux.append(j)
    viables = [j for j in jeux if j["viable"]]
    for j in jeux:
        j["non_domine"] = j["viable"] and not any(domine(o, j) for o in viables if o is not j)
    actuel = next(j for j in jeux if j["jeu"] == "actuel")
    nets = [o for o in viables if o is not actuel and domine(o, actuel, net=True)]
    pareto = [j for j in jeux if j["non_domine"]]
    plages = {}
    for n, lib, v in POIDS:
        fs = sorted(j[f"f_{n}"] for j in pareto)
        if not fs:
            plages[n] = None
            continue
        lo, hi = fs[0], fs[-1]
        bord_bas, bord_haut = lo <= 1 / FACTEUR_MAX * 1.5, hi >= FACTEUR_MAX / 1.5
        plages[n] = {"libelle": lib, "valeur_actuelle": v, "facteur_min": lo, "facteur_max": hi,
                     "valeur_min": v * lo, "valeur_max": v * hi,
                     "ouverte_en_bas": bord_bas, "ouverte_en_haut": bord_haut,
                     "actuelle_dans_plage": lo <= 1 <= hi}
    bilan = {"jeux_testes": len(jeux), "jeux_viables": len(viables), "jeux_non_domines": len(pareto),
             "actuel_viable": actuel["viable"], "actuel_non_domine": actuel["non_domine"],
             "actuel_nettement_domine_par": [o["jeu"] for o in nets],
             "lits_places_en_trop_toutes_solutions": sum(j["lits_ou_places_en_trop"] for j in jeux),
             "plages_des_jeux_non_domines": plages, "poids_fixes": FIXES,
             "tolerances": {"reportes": TOL_REPORTS, "occupation_pts": TOL_OCC}}
    return jeux, bilan


def figures(jeux: list[dict], bilan: dict, sortie: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for j in jeux:
        style = dict(marker="o", s=30, facecolors="none" if not j["viable"] else ("tab:green" if j["non_domine"] else "0.6"),
                     edgecolors="tab:red" if not j["viable"] else "k")
        ax.scatter(j["occupation_pct"], j["reportes"], **style)
    a = next(j for j in jeux if j["jeu"] == "actuel")
    ax.scatter(a["occupation_pct"], a["reportes"], marker="*", s=250, color="tab:blue", zorder=5, label="poids actuels")
    ax.scatter([], [], marker="o", color="tab:green", edgecolors="k", label="viable, non dominé")
    ax.scatter([], [], marker="o", color="0.6", edgecolors="k", label="viable, dominé")
    ax.scatter([], [], marker="o", facecolors="none", edgecolors="tab:red", label="non viable (validateur)")
    ax.set(xlabel="Occupation du bloc (%)", ylabel="Patients reportés après l'horizon",
           title="Jeux de poids tirés ensemble (moyenne des instances et des graines)")
    ax.legend(fontsize=8)
    fig.savefig(sortie / "compromis.png", dpi=200)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
    for k, (n, lib, v) in enumerate(POIDS):
        p = bilan["plages_des_jeux_non_domines"].get(n)
        ax.plot([1 / FACTEUR_MAX, FACTEUR_MAX], [k, k], color="0.85", lw=6)
        if p:
            ax.plot([p["facteur_min"], p["facteur_max"]], [k, k], color="tab:green", lw=6)
        ax.plot(1, k, "o", color="tab:blue")
    ax.set(xscale="log", yticks=range(len(POIDS)), yticklabels=[f"{lib} ({v:g})" for _, lib, v in POIDS],
           xlabel="facteur appliqué au poids actuel", title="Facteurs présents dans les jeux non dominés (vert) ; point : actuel")
    fig.savefig(sortie / "plages.png", dpi=200)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sensibilité des poids de la fonction score N2 (poids variés ensemble)")
    ap.add_argument("--tirages", type=int, default=30, help="jeux de poids tirés (en plus du jeu actuel)")
    ap.add_argument("--graines", type=int, default=2)
    ap.add_argument("--budget", type=float, default=5.0, help="secondes de RS par essai")
    ap.add_argument("--coeurs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--graine-tirage", type=int, default=2026)
    ap.add_argument("--sortie", default=str(SORTIE))
    o = ap.parse_args(argv)
    sortie = Path(o.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    rng = random.Random(o.graine_tirage)
    tirages = {"actuel": {n: 1.0 for n, _, _ in POIDS}}
    for k in range(o.tirages):
        tirages[f"t{k:03d}"] = {n: math.exp(rng.uniform(-math.log(FACTEUR_MAX), math.log(FACTEUR_MAX))) for n, _, _ in POIDS}
    taches = [(nom, jeu, fac, g, o.budget) for jeu, fac in tirages.items() for nom in INSTANCES
              for g in range(1, o.graines + 1)]
    print(f"{len(taches)} essais de {o.budget:g} s sur {o.coeurs} cœurs : ≈ {len(taches) * o.budget / o.coeurs / 60:.1f} min")
    t0 = time.perf_counter()
    with mp.get_context("spawn").Pool(o.coeurs) as pool:
        essais = pool.map(essai, taches)
    jeux, bilan = analyser(essais, tirages)
    import csv
    for nom, lignes in (("essais.csv", essais), ("jeux.csv", jeux)):
        with open(sortie / nom, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lignes[0]))
            w.writeheader()
            w.writerows(lignes)
    bilan.update({"tirages": o.tirages, "graines": o.graines, "budget_s": o.budget, "facteur_max": FACTEUR_MAX,
                  "instances": INSTANCES, "duree_s": time.perf_counter() - t0})
    (sortie / "sensibilite.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    figures(jeux, bilan, sortie)
    print(json.dumps({k: v for k, v in bilan.items() if k != "plages_des_jeux_non_domines"}, ensure_ascii=False, indent=1))
    return bilan


if __name__ == "__main__":
    main()
