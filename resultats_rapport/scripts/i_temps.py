# -*- coding: utf-8 -*-
"""
Tâche I : temps de calcul RÉELS (perf_counter), séparés du temps simulé du SMA et des budgets alloués.
Relit les sorties des tâches C, D/E, G, H et mesure en plus : génération d'instance, validateur, reconstruction de
l'état du site (rejeu des événements par sma_service.simuler), tous sur la machine décrite dans environnement.md.
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, time as heure, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from commun_rapport import (AGREGEES, METHODES, SORTIE, ecrire_csv, lire_csv,  # noqa: E402
                            resume_stat, sauver_figure)

SCRIPT = "scripts/i_temps.py"


def _mesurer(f, n):
    v = []
    for _ in range(n):
        t0 = time.perf_counter()
        f()
        v.append(time.perf_counter() - t0)
    return v


def main():
    lignes = [dict(source="c_ml.py", **l_) for l_ in lire_csv(AGREGEES / "temps_ml.csv")]
    n1 = lire_csv(SORTIE / "n1_resultats.csv")
    n2 = lire_csv(SORTIE / "n2_resultats.csv")
    for niv, rows in (("N1", n1), ("N2", [r for r in n2 if r["campagne"] == "N2_reference"])):
        for m in ["glouton", "premier créneau"] + METHODES:
            ls = [r for r in rows if r["methode"] == m]
            if not ls:
                continue
            t = [float(r["temps_reel_s"]) for r in ls]
            ev = [float(r["evaluations"]) for r in ls]
            s = resume_stat(t)
            lignes.append({"source": "de_optimisation.py", "composant": f"{niv} {m}", "mesure": "temps réel (s), budget "
                           + (ls[0]["budget_s"]), "valeur": s["moyenne"], "n": s["n"], "max": s["max"],
                           "depassement_budget_max_pct": (100 * (s["max"] - float(ls[0]["budget_s"])) / float(ls[0]["budget_s"])
                                                          if float(ls[0]["budget_s"]) else None),
                           "evaluations_moyennes": statistics.fmean(ev)})
    # mesures directes
    import hybridation as H
    import structures_communes as SC
    import validation as VA
    from parametres import LUNDI_REFERENCE as L0
    t_inst = _mesurer(lambda: H.instance_v28(L0, 4, graine=43, charge=0.9), 5)
    inst = H.etendre_horizon(H.instance_v28(L0, 4, graine=43, charge=0.9), 3)
    sol = SC.construire_meilleure_affectation_initiale(inst)
    t_val = _mesurer(lambda: VA.valider_niveau2(inst, sol), 20)
    t_eval = _mesurer(lambda: SC.evaluer_niveau2(inst, sol), 20)
    t_glouton = _mesurer(lambda: SC.construire_meilleure_affectation_initiale(inst), 3)
    from orchestre import programme as P
    from orchestre import sma_service as S
    t_prog = _mesurer(lambda: P.calculer_programme(L0, "glouton"), 1)
    prog = P.calculer_programme(L0, "glouton")
    t_rejeu = _mesurer(lambda: S.simuler(prog, [], datetime.combine(L0 + timedelta(days=2), heure(10))), 5)
    for nom, v in (("génération instance N2 v28 4 semaines", t_inst), ("validateur indépendant N2", t_val),
                   ("évaluation complète F2", t_eval), ("glouton multi-départ N2 (40 essais)", t_glouton),
                   ("calcul du programme du site (glouton)", t_prog),
                   ("reconstruction de l'état du site (rejeu SMA, 0 événement, mercredi 10 h)", t_rejeu)):
        s = resume_stat(v)
        lignes.append({"source": "i_temps.py", "composant": nom, "mesure": "médiane (s)", "valeur": s["mediane"],
                       "n": s["n"], "max": s["max"]})
    # SMA : temps réel par événement et par stratégie
    for l_ in lire_csv(SORTIE / "sma_evenements_agreges.csv"):
        lignes.append({"source": "h_sma.py", "composant": f"SMA {l_['strategie']} {l_['type_evenement']}",
                       "mesure": "médiane (s)", "valeur": float(l_["median_s"]), "n": l_["n"], "max": float(l_["max_s"]),
                       "p95": float(l_["p95_s"])})
    for l_ in lire_csv(SORTIE / "saturation_resultats.csv"):
        lignes.append({"source": "g_saturation_robustesse.py", "composant": f"saturation : {l_['variante']}",
                       "mesure": "temps réel (s)", "valeur": float(l_["temps_reel_s"]), "n": 1})
    ecrire_csv(SORTIE / "temps.csv", lignes)

    # Temps pour atteindre un seuil de qualité fixé avant analyse : score ≤ 1,05 × meilleure solution FAISABLE
    import json
    conv = json.loads((AGREGEES / "convergence.json").read_text(encoding="utf-8"))
    ref = [r for r in n2 if r["campagne"] == "N2_reference"]
    best = min(float(r["score_recherche"]) for r in ref if r["faisable"] == "True" and r["score_recherche"])
    seuil = 1.05 * best
    atteint = []
    for m in METHODES:
        ts = []
        for c in conv:
            if c["campagne"] == "N2_reference" and c["methode"] == m:
                t = next((p[0] for p in c["convergence"] if p[1] <= seuil), None)
                ts.append(t)
        ok = [t for t in ts if t is not None]
        atteint.append({"methode": m, "seuil_score_recherche": seuil, "executions": len(ts), "atteint": len(ok),
                        "temps_median_s": statistics.median(ok) if ok else None})
    ecrire_csv(AGREGEES / "temps_pour_seuil.csv", atteint)

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    meth = [m for m in METHODES]
    vals = [[float(r["evaluations"]) / max(1e-9, float(r["temps_reel_s"])) for r in ref if r["methode"] == m] for m in meth]
    ax.boxplot(vals, tick_labels=meth, patch_artist=True)
    ax.set(yscale="log", ylabel="Évaluations par seconde (temps réel)", title="N2 référence : débit d'évaluation (10 graines)")
    plt.setp(ax.get_xticklabels(), rotation=20)
    sauver_figure(fig, "temps_debit_n2")
    plt.close(fig)
    for a in atteint:
        print(a)


if __name__ == "__main__":
    main()
