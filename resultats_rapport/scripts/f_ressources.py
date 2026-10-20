# -*- coding: utf-8 -*-
"""
Tâche F : profils d'occupation bloc / lits / places sur les 4 semaines v28 (cohorte de référence, première graine
faisable de chaque méthode), sorties à midi et admissions du même jour, et nuage des compromis taux d'occupation du bloc / pic
de lits sur toutes les exécutions à 100 % de charge. Lit les solutions synthétiques enregistrées par la campagne E.

Le modèle ne contient pas d'heure d'admission : les « admissions du soir » ne sont pas mesurables ; on compte les
admissions du jour (patients dont la première nuit commence ce jour) et les sorties à midi (fin de séjour).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from commun_rapport import (AGREGEES, COULEURS, MARQUEURS, SORTIE, ecrire_csv, enregistrer_manifeste, lire_csv,  # noqa: E402
                            sauver_figure)

SCRIPT = "scripts/f_ressources.py"
ORDRE = ["glouton", "premier créneau", "RS seul", "TABOU seul", "AGS seul", "memetique", "AGS>RS>TABOU", "RS>AGS>TABOU"]


def main():
    import hybridation as H
    import structures_communes as SC
    from parametres import LUNDI_REFERENCE as L0
    inst = H.etendre_horizon(H.instance_v28(L0, 4, graine=43, charge=0.90), H.NB_SEMAINES_REPORT)
    sols = json.loads((AGREGEES / "solutions_synthetiques.json").read_text(encoding="utf-8"))
    # règle de l'équipe : seules les solutions faisables sont proposées -> pour chaque méthode, la plus petite graine
    # dont la solution est faisable (le glouton est le départ commun, montré pour référence)
    faisable = {(r["methode"], int(r["graine"])): r["faisable"] == "True"
                for r in lire_csv(SORTIE / "n2_resultats.csv") if r["campagne"] == "N2_reference"}
    ref, graine_retenue = {}, {}
    for s in sorted((s for s in sols if s["campagne"] == "N2_reference"), key=lambda s: int(s["graine"])):
        m = s["methode"]
        if m not in ref and (m == "glouton" or faisable.get((m, int(s["graine"])))):
            ref[m] = {int(k): v for k, v in s["solution"].items()}
            graine_retenue[m] = int(s["graine"])
    jours = [L0 + timedelta(days=k) for k in range(28 + 21)]
    V, P, h = inst.vacations, inst.patients, inst.hebergement
    cap_jour = defaultdict(float)
    for v in V.values():
        if not v.supplementaire:
            cap_jour[v.jour] += v.capacite_utile_minutes
    lignes, profils = [], {}
    for m in [x for x in ORDRE if x in ref]:
        aff = ref[m]
        sol = SC.SolutionPatients(aff)
        lits, places = SC.calculer_occupation(inst, sol)
        lj, pj = SC.par_jour(lits), SC.par_jour(places)
        charge = defaultdict(float)
        sorties, admissions = Counter(), Counter()
        for pid, vid in aff.items():
            if vid is None:
                continue
            p, v = P[pid], V[vid]
            if not v.supplementaire:
                charge[v.jour] += p.duree_bloc
            if not p.ambulatoire:
                admissions[v.jour - timedelta(days=p.nuits_pre_op)] += 1
                sorties[v.jour + timedelta(days=p.nuits_post_op)] += 1
        bloc = {j: 100 * charge[j] / cap_jour[j] for j in cap_jour}
        rotation = sum(min(sorties[j], admissions[j]) for j in jours)
        matin = {j: places.get(SC.DemiJournee(j, False), 0) for j in jours}
        apm = {j: places.get(SC.DemiJournee(j, True), 0) for j in jours}
        profils[m] = {"bloc": bloc, "lits": lj, "matin": matin, "apm": apm, "sorties": sorties, "admissions": admissions}
        horizon = [j for j in jours if j < L0 + timedelta(days=28)]
        lignes.append({"methode": m, "graine": graine_retenue[m], "faisable": faisable.get((m, graine_retenue[m])), "occupation_bloc_moyenne_pct": float(np.mean(list(bloc.values()))),
                       "jours_bloc_au_dela_capacite_utile": sum(x > 100 for x in bloc.values()),
                       "pic_lits_horizon": max((lj.get(j, 0) for j in horizon), default=0),
                       "nuits_lits_au_cap_programmable": sum(lj.get(j, 0) >= h.cap_lits for j in jours),
                       "lits_programmables": h.cap_lits, "reserve": h.reserve_lits,
                       "pic_places_matin": max(matin.values()), "pic_places_apres_midi": max(apm.values()),
                       "demi_journees_places_pleines": sum(x >= h.cap_places for x in list(matin.values()) + list(apm.values())),
                       "sorties_a_midi": sum(sorties.values()), "admissions": sum(admissions.values()),
                       "jours_avec_sortie_et_admission": sum(1 for j in jours if sorties[j] and admissions[j]),
                       "lits_reutilises_le_jour_de_sortie_max": rotation,
                       "occupation_lits_au_dela_horizon": sum(lj.get(j, 0) for j in jours if j >= L0 + timedelta(days=28))})
    ecrire_csv(SORTIE / "ressources_resume.csv", lignes)

    figs = []
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True, layout="constrained")
    montrer = [m for m in ("glouton", "premier créneau", "TABOU seul", "memetique") if m in profils]
    for m in montrer:
        pr = profils[m]
        xs = sorted(pr["bloc"])
        axes[0].plot(xs, [pr["bloc"][j] for j in xs], marker=MARQUEURS[m], color=COULEURS[m], label=m, lw=1)
        axes[1].plot(jours, [pr["lits"].get(j, 0) for j in jours], color=COULEURS[m], label=m, lw=1.2)
        axes[2].plot(jours, [max(pr["matin"][j], pr["apm"][j]) for j in jours], color=COULEURS[m], label=m, lw=1.2)
    axes[0].axhline(100, color="k", ls=":")
    axes[1].axhline(h.cap_lits, color="k", ls=":")
    axes[1].axhline(h.cap_lits + h.reserve_lits, color="r", ls=":")
    axes[2].axhline(h.cap_places, color="k", ls=":")
    axes[0].set(ylabel="Bloc : % de la capacité utile")
    axes[1].set(ylabel="Lits occupés (nuit)", title="pointillé noir : 27 lits programmables ; rouge : 30 avec la réserve")
    axes[2].set(ylabel="Places (pic de la journée)", xlabel="Jour (4 semaines + 3 semaines de report)")
    axes[0].legend(fontsize=8, ncol=4)
    fig.suptitle("Profils d'occupation, cohorte de référence (première graine faisable ; glouton = départ)")
    figs += sauver_figure(fig, "ressources_profils")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 3.8), layout="constrained")
    m = "memetique" if "memetique" in profils else montrer[0]
    pr = profils[m]
    ax.bar(jours, [pr["sorties"][j] for j in jours], width=0.4, align="edge", color="0.3", label="sorties à midi")
    ax.bar(jours, [-pr["admissions"][j] for j in jours], width=0.4, align="edge", color="0.7", label="admissions (négatif)")
    ax.plot(jours, [pr["lits"].get(j, 0) for j in jours], "k-", label="lits occupés la nuit")
    ax.set(title=f"Lits : sorties à midi et admissions du même jour ({m}, graine {graine_retenue[m]}) — heure d'admission non modélisée",
           ylabel="Patients")
    ax.legend(fontsize=8)
    figs += sauver_figure(fig, "ressources_lits_rotation")
    plt.close(fig)

    n2 = [l_ for l_ in lire_csv(SORTIE / "n2_resultats.csv") if l_["charge_pct"] == "100" and l_["campagne"] != "N2_budgets"]
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for m in ORDRE:
        ls = [l_ for l_ in n2 if l_["methode"] == m]
        if ls:
            fa = [l_["faisable"] == "True" for l_ in ls]
            x = np.array([float(l_["taux_occupation_bloc_pct"]) for l_ in ls])
            y = np.array([float(l_["pic_lits"]) for l_ in ls])
            ax.scatter(x[fa], y[fa], marker=MARQUEURS[m], color=COULEURS[m], label=m, s=28)
            ax.scatter(x[[not f for f in fa]], y[[not f for f in fa]], marker=MARQUEURS[m], facecolors="none",
                       edgecolors=COULEURS[m], s=28)
    ax.set(xlabel="Taux d'occupation du bloc (%)", ylabel="Pic de lits occupés",
           title="Compromis observés à 100 % de charge (3 cohortes ; symbole creux = non faisable, non proposé)")
    ax.legend(fontsize=7)
    figs += sauver_figure(fig, "ressources_compromis")
    plt.close(fig)
    enregistrer_manifeste("F6/F8/F13 ressources", ["ressources_resume.csv", "donnees_agregees/solutions_synthetiques.json",
                                                   "n2_resultats.csv"], SCRIPT, note=", ".join(figs))
    print(f"ressources : {len(lignes)} méthodes")


if __name__ == "__main__":
    main()
