# -*- coding: utf-8 -*-
"""
Pilote court (branche v3) : effet de (1) la tolérance de dépassement + solution proposée = meilleure faisable
rencontrée, (2) un polissage plus léger des enfants dans le mode mémétique (iterations_par_enfant), sur la cohorte de
référence (charge 100 %, cohorte 43), 3 graines, 10 s. Classement sur le critère optimisé (F2 + report).
PILOTE : sert à décider, pas un résultat final.
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import random
import time

from commun_rapport import AGREGEES, METHODES, ecrire_csv

SORTIE = AGREGEES / "v3_pilote"


def executer(t):
    import hybridation as H
    from parametres import LUNDI_REFERENCE
    inst = H.etendre_horizon(H.instance_v28(LUNDI_REFERENCE, 4, graine=43, charge=0.90), H.NB_SEMAINES_REPORT)
    rl = H.ParametresRechercheLocale(**({"iterations_par_enfant": t["iter_enfant"]} if t["iter_enfant"] else {}))
    with contextlib.redirect_stdout(io.StringIO()):
        r = H._executer_niveau(2, inst, [t["mode"]], 10.0, t["graine"], rl)[0]
    i = r.indicateurs
    return {**t, "variante": t["mode"] + (f" (polissage {t['iter_enfant']} it.)" if t["iter_enfant"] else ""),
            "faisable": r.faisable, "violations": r.validation.get("par_type"), "score_commun": r.score_final,
            "score_objectif": r.score_recherche, "penalite_report": r.detail_score.get("report"),
            "generations": r.compteurs.get("generations", 0), "reportes": i.patients_en_supp,
            "occupation_bloc_pct": i.taux_occupation_bloc_pct, "pic_lits": i.pic_lits, "temps_s": r.temps_calcul_s}


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    taches = [dict(mode=m, graine=g, iter_enfant=None) for m in METHODES for g in (1, 2, 3)]
    taches += [dict(mode="memetique", graine=g, iter_enfant=k) for k in (1, 3) for g in (1, 2, 3)]
    random.Random(2026).shuffle(taches)
    t0 = time.perf_counter()
    with mp.get_context("spawn").Pool(4) as pool:
        lignes = pool.map(executer, taches)
    ecrire_csv(SORTIE / "pilote_v3.csv", sorted(lignes, key=lambda l_: (l_["variante"], l_["graine"])))
    print(f"{len(lignes)} exécutions en {time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    main()
