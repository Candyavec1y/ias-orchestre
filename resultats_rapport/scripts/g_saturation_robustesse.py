# -*- coding: utf-8 -*-
"""
Tâche G : saturation (étude du projet interface/tests/saturation.py, appelée sans modification) et robustesse des
programmes N2 de la campagne E à des perturbations (durées opératoires, capacités), une dimension à la fois.

Robustesse : chaque solution N2 PROPOSÉE (faisable) de la cohorte de référence, plus le départ glouton pour
référence, est RÉÉVALUÉE (sans réoptimisation) avec des durées multipliées par un facteur fixe (0,9 / 1,1 / 1,2) ou par
un bruit lognormal (σ = 0,25 ≈ erreur relative du modèle de durée, 20 tirages), puis avec moins de lits ou de places.
Mesures : dépassements de la capacité utile (marge de 10 %) et de la durée TOTALE des vacations (heures
supplémentaires), violations du validateur. Les patients sont synthétiques (cohorte DEMO).
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import replace

from commun_rapport import AGREGEES, SORTIE, ecrire_csv, resume_stat

SCRIPT = "scripts/g_saturation_robustesse.py"


def saturation():
    sys.path.insert(0, str(SORTIE.parent / "interface" / "tests"))
    import saturation as SAT
    import structures_communes as SC
    h = SC.HEBERGEMENT_SITE
    variantes = [("site (30 lits dont 3 réserve, 20 places)", dict(hebergement=h, analyser_ressources=True)),
                 ("site, graine 43", dict(hebergement=h, graine=43, analyser_ressources=False)),
                 ("site, graine 44", dict(hebergement=h, graine=44, analyser_ressources=False)),
                 ("lits réduits (20 dont 3 réserve)", dict(hebergement=SC.ParametresHebergement(20, h.places_ambulatoires_par_jour, 3), analyser_ressources=False)),
                 ("places réduites (10)", dict(hebergement=SC.ParametresHebergement(h.lits_disponibles_par_jour, 10, h.reserve_lits), analyser_ressources=False)),
                 ("réserve 6 lits", dict(hebergement=SC.ParametresHebergement(h.lits_disponibles_par_jour, h.places_ambulatoires_par_jour, 6), analyser_ressources=False)),
                 ("patients acceptant un confrère", dict(hebergement=h, confrere=True, analyser_ressources=False))]
    lignes, courbes = [], []
    for nom, kw in variantes:
        t0 = time.perf_counter()
        r = SAT.etudier(semaines=4, **kw)
        hb = r.hebergement
        lignes.append({"variante": nom, "graine": kw.get("graine", SAT.GRAINE_SATURATION), "lits": hb.lits_disponibles_par_jour,
                       "reserve": hb.reserve_lits, "places": hb.places_ambulatoires_par_jour, "patients_inscrits": r.n_patients,
                       "minutes_vacation": r.minutes_vacation, "minutes_utiles": r.minutes_utiles,
                       "operes_dans_horizon": r.places_dans_horizon, "rang_premier_debordement": r.premier_debordement,
                       "liste_attente": r.en_attente, "occupation_vacation_pct": r.occupation_finale_pct,
                       "occupation_utile_pct": r.occupation_utile_pct, "pic_lits": r.pic_lits,
                       "jours_lits_pleins": r.jours_lits_pleins, "pic_places": r.pic_places,
                       "jours_places_pleines": r.jours_places_pleines, "debordes_hospitalises_pct": r.debordes_hospitalises_pct,
                       **{f"inscrits_pour_{k}pct": v for k, v in r.seuils.items()},
                       "capacite_lits_illimites": r.capacite_sans_limite_lits,
                       "capacite_places_illimitees": r.capacite_sans_limite_places,
                       "ressource_limitante": r.ressource_limitante if kw.get("analyser_ressources") else "NON EXÉCUTÉ",
                       "erreurs_coherence": r.erreurs_coherence, "temps_reel_s": time.perf_counter() - t0})
        courbes.append({"variante": nom, "courbe": r.courbe})
        print(f"  saturation {nom} : {r.places_dans_horizon} opérés ({time.perf_counter() - t0:.0f} s)", flush=True)
    ecrire_csv(SORTIE / "saturation_resultats.csv", lignes)
    (AGREGEES / "saturation_courbes.json").write_text(json.dumps(courbes), encoding="utf-8")
    return lignes, courbes


def robustesse():
    import hybridation as H
    import structures_communes as SC
    import validation as VA
    from parametres import LUNDI_REFERENCE
    sols = json.loads((AGREGEES / "solutions_synthetiques.json").read_text(encoding="utf-8"))
    base = H.instance_v28(LUNDI_REFERENCE, 4, graine=43, charge=0.90)
    inst = H.etendre_horizon(base, H.NB_SEMAINES_REPORT)
    # règle de l'équipe : seules les solutions faisables sont proposées ; le glouton (départ commun) sert de référence
    from commun_rapport import lire_csv
    faisable = {(r["methode"], int(r["graine"])): r["faisable"] == "True"
                for r in lire_csv(SORTIE / "n2_resultats.csv") if r["campagne"] == "N2_reference"}
    choisies = [s for s in sols if s["campagne"] == "N2_reference"
                and (s["methode"] == "glouton" or faisable[(s["methode"], int(s["graine"]))])]

    def mesurer(inst2, aff):
        charge = {}
        for pid, vid in aff.items():
            if vid is not None:
                charge[vid] = charge.get(vid, 0) + inst2.patients[pid].duree_bloc
        V = inst2.vacations
        au_dela_utile = sum(max(0, c - V[v].capacite_utile_minutes) for v, c in charge.items())
        au_dela_total = sum(max(0, c - V[v].duree_minutes) for v, c in charge.items())
        vac_hs = sum(c > V[v].duree_minutes for v, c in charge.items())
        val = VA.valider_niveau2(inst2, SC.SolutionPatients(aff))
        pt = val.par_type()
        return {"minutes_au_dela_capacite_utile": au_dela_utile, "minutes_heures_supplementaires": au_dela_total,
                "vacations_en_heures_supplementaires": vac_hs, "faisable": val.faisable,
                "violations_lits": pt.get("lits", 0), "violations_places": pt.get("places ambulatoires", 0),
                "violations_capacite_vacation": pt.get("capacité de vacation", 0)}

    def avec_durees(facteurs: dict):
        pts = {pid: replace(p, duree_bloc=max(5, int(round(p.duree_bloc * facteurs[pid])))) for pid, p in inst.patients.items()}
        return SC.InstanceNiveau2(pts, inst.vacations, inst.hebergement, inst.noms_chirurgiens, inst.nom)

    perturbations = [("durées ×0,9", lambda rng: {p: 0.9 for p in inst.patients}),
                     ("durées ×1,0 (nominal)", lambda rng: {p: 1.0 for p in inst.patients}),
                     ("durées ×1,1", lambda rng: {p: 1.1 for p in inst.patients}),
                     ("durées ×1,2", lambda rng: {p: 1.2 for p in inst.patients})]
    lignes = []
    for s in choisies:
        aff = {int(k): v for k, v in s["solution"].items()}
        for nom, fab in perturbations:
            lignes.append({"methode": s["methode"], "graine": s["graine"], "perturbation": nom,
                           **mesurer(avec_durees(fab(None)), aff)})
        for k in range(20):                      # bruit lognormal : moyenne 1, σ log = 0,25
            rng = random.Random(1000 + k)
            fac = {p: math.exp(rng.gauss(-0.25 ** 2 / 2, 0.25)) for p in inst.patients}
            lignes.append({"methode": s["methode"], "graine": s["graine"], "perturbation": "bruit lognormal σ=0,25",
                           "tirage": k, **mesurer(avec_durees(fac), aff)})
        for nom, hb in (("lits 24 (−6)", SC.ParametresHebergement(24, 20, 3)), ("places 15 (−5)", SC.ParametresHebergement(30, 15, 3))):
            i2 = SC.InstanceNiveau2(inst.patients, inst.vacations, hb, inst.noms_chirurgiens, inst.nom)
            lignes.append({"methode": s["methode"], "graine": s["graine"], "perturbation": nom, **mesurer(i2, aff)})
    ecrire_csv(SORTIE / "robustesse_resultats.csv", lignes)
    return lignes


def figures(sat, courbes, rob):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from commun_rapport import COULEURS, MARQUEURS, sauver_figure
    figs = []
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for c in courbes:
        ax.plot([p[0] for p in c["courbe"]], [p[1] for p in c["courbe"]], label=c["variante"], lw=1.2)
    ax.axhline(90, color="k", ls=":", lw=1)
    ax.text(5, 91, "capacité utile (90 % du temps de vacation)", fontsize=8)
    ax.set(xlabel="Patients inscrits (ordre d'arrivée)", ylabel="Temps de vacation programmé dans l'horizon (%)",
           title="Saturation du bloc sur 4 semaines (v28, patients au profil réel)")
    ax.legend(fontsize=7)
    figs += sauver_figure(fig, "saturation_courbes")
    plt.close(fig)

    meth = ["glouton", "premier créneau", "RS seul", "TABOU seul", "AGS seul", "memetique", "AGS>RS>TABOU", "RS>AGS>TABOU"]
    perts = ["durées ×0,9", "durées ×1,0 (nominal)", "durées ×1,1", "durées ×1,2", "bruit lognormal σ=0,25"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), layout="constrained")
    for m in meth:
        y1 = [resume_stat([l_["minutes_heures_supplementaires"] for l_ in rob if l_["methode"] == m and l_["perturbation"] == p]).get("moyenne") for p in perts]
        y2 = [100 * sum(l_["faisable"] for l_ in rob if l_["methode"] == m and l_["perturbation"] == p)
              / max(1, sum(1 for l_ in rob if l_["methode"] == m and l_["perturbation"] == p)) for p in perts]
        axes[0].plot(range(len(perts)), y1, marker=MARQUEURS[m], color=COULEURS[m], label=m)
        axes[1].plot(range(len(perts)), y2, marker=MARQUEURS[m], color=COULEURS[m], label=m)
    for ax in axes:
        ax.set_xticks(range(len(perts)), perts, rotation=15)
    axes[0].set(ylabel="Minutes au-delà de la durée totale des vacations (moyenne)", title="Heures supplémentaires induites")
    axes[1].set(ylabel="Programmes encore faisables (%)", title="Faisabilité après perturbation (sans réoptimisation)")
    axes[0].legend(fontsize=7)
    figs += sauver_figure(fig, "robustesse_durees")
    plt.close(fig)


if __name__ == "__main__":
    t0 = time.perf_counter()
    rob = robustesse()
    print(f"robustesse : {len(rob)} lignes ({time.perf_counter() - t0:.0f} s)", flush=True)
    if len(sys.argv) > 1 and sys.argv[1] == "robustesse":      # saturation déjà calculée : relue
        from commun_rapport import lire_csv
        sat = lire_csv(SORTIE / "saturation_resultats.csv")
        courbes = json.loads((AGREGEES / "saturation_courbes.json").read_text(encoding="utf-8"))
    else:
        sat, courbes = saturation()
    figures(sat, courbes, rob)
    print(f"Terminé en {time.perf_counter() - t0:.0f} s")
