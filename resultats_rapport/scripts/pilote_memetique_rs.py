# -*- coding: utf-8 -*-
"""
PILOTE (branche v3) : polissage des enfants du mode mémétique par un RS court (ParametresRechercheLocale
polissage_enfant="rs", iterations_rs_enfant = 300 ou 1 500), comparé au mémétique actuel (Tabou 15 itérations),
à AGS>RS>TABOU et à RS seul. Cohorte de référence (charge 100 %, cohorte 43), 5 graines, budgets 10 s et 30 s.
Critère : score de recherche (F2 + report) de la solution proposée ; Wilcoxon apparié par graine.
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import random
import statistics
import time

from scipy import stats

from commun_rapport import AGREGEES, ecrire_csv

SORTIE = AGREGEES / "v3_pilote"
VARIANTES = {"RS seul": ("RS seul", {}), "AGS>RS>TABOU": ("AGS>RS>TABOU", {}), "memetique": ("memetique", {}),
             "memetique RS 300": ("memetique", {"polissage_enfant": "rs", "iterations_rs_enfant": 300}),
             "memetique RS 1500": ("memetique", {"polissage_enfant": "rs", "iterations_rs_enfant": 1500})}


def executer(t):
    import hybridation as H
    from parametres import LUNDI_REFERENCE
    inst = H.etendre_horizon(H.instance_v28(LUNDI_REFERENCE, 4, graine=43, charge=0.90), H.NB_SEMAINES_REPORT)
    mode, kw = VARIANTES[t["variante"]]
    with contextlib.redirect_stdout(io.StringIO()):
        r = H._executer_niveau(2, inst, [mode], t["budget"], t["graine"], H.ParametresRechercheLocale(**kw))[0]
    return {**t, "faisable": r.faisable, "score_objectif": r.score_recherche, "score_commun": r.score_final,
            "generations": r.compteurs.get("generations", 0), "reportes": r.indicateurs.patients_en_supp,
            "occupation_bloc_pct": r.indicateurs.taux_occupation_bloc_pct, "temps_s": r.temps_calcul_s}


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    taches = [dict(variante=v, budget=b, graine=g) for v in VARIANTES for b in (10.0, 30.0) for g in range(1, 6)]
    random.Random(2026).shuffle(taches)
    t0 = time.perf_counter()
    with mp.get_context("spawn").Pool(4) as pool:
        lignes = pool.map(executer, taches)
    ecrire_csv(SORTIE / "pilote_memetique_rs.csv", sorted(lignes, key=lambda l_: (l_["budget"], l_["variante"], l_["graine"])))
    tests = []
    for b in (10.0, 30.0):
        sc = {v: {l_["graine"]: l_["score_objectif"] for l_ in lignes if l_["variante"] == v and l_["budget"] == b}
              for v in VARIANTES}
        for v in ("memetique RS 300", "memetique RS 1500"):
            for ref in ("RS seul", "memetique", "AGS>RS>TABOU"):
                d = [sc[v][g] - sc[ref][g] for g in range(1, 6)]
                w = stats.wilcoxon([sc[v][g] for g in range(1, 6)], [sc[ref][g] for g in range(1, 6)])
                tests.append({"budget_s": b, "variante": v, "contre": ref, "diff_mediane": statistics.median(d),
                              "variante_meilleure": sum(x < 0 for x in d), "p": w.pvalue})
    ecrire_csv(SORTIE / "pilote_memetique_rs_tests.csv", tests)
    print(f"{len(lignes)} exécutions en {time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    main()
