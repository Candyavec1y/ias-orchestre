# -*- coding: utf-8 -*-
"""
metaheuristiques/justifier_poids.py — Justification des points de pénalité de la fonction score N2
====================================================================================================

Poids testés (valeurs actuelles) :
    non_place 8000 (par patient non placé)        depassement_vac 100 (par minute au-delà de la capacité utile)
    bloc_inoccupe 1 (par minute de bloc vide)     report 100 / semaine x poids de priorité (1, 2, 3, 5) -> 200 en prio 2
    lit 5000 (par lit-jour en trop)               var_lits 20 (lissage des lits)
    place 5000 (par place-jour en trop)           var_places 20 (lissage des places)

Méthode : UN poids varie à la fois (facteur x0,01 ... x100), les autres restent à leur valeur actuelle. Pour chaque
valeur, le Tabou du projet optimise le planning (instance d'étude + planning v28, capacités réduites, report possible sur
3 semaines) et on mesure si le planning obtenu est VIABLE :
    règles strictes   aucun lit-jour ni place-jour au-delà de la capacité, aucun patient non placé,
                      au plus MAX_DEP (60) minutes de dépassement des vacations sur la semaine
    dominance         rejeté si un autre planning réalisable fait NETTEMENT mieux à la fois sur les reports
                      (au moins TOL_REPORTS = 2 patients de moins) ET sur l'occupation des vacations (au moins
                      TOL_OCC = 3 points de plus), sans reporter plus de patients prioritaires
    prioritaires      au plus TOL_PRIO (2) patients de priorité 3-4 reportés de plus que le meilleur planning réalisable
Un poids est JUSTIFIÉ si sa valeur actuelle est dans la plage viable ; sinon le script propose la valeur au centre
(géométrique) de la plage viable.

Sorties (resultats_justification/) :
    plages_viables.png       une ligne par poids : plage viable en vert, valeur actuelle, valeur recommandée
    effets_<groupe>.png      pour chaque poids, les 4 indicateurs en fonction du facteur (bande verte = viable)
    poids_justifies.json     poids actuels, plages viables, poids recommandés ; essais.csv

    python metaheuristiques/justifier_poids.py                 # ≈ 5 min (budget 300 s)
    python metaheuristiques/justifier_poids.py --budget 120 --graines 1
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import os
import random
import statistics
import time
from pathlib import Path

import sys
import warnings
from datetime import date

_ICI = Path(__file__).resolve().parent                    # fichier autonome : cherche les modules du dépôt
for _d in (_ICI, _ICI.parent / "commun", _ICI.parent / "metaheuristiques", _ICI.parent / "planning_vacations"):
    if _d.is_dir() and str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
warnings.filterwarnings("ignore")

try:
    import hybride_ags_rs_tabou as H
except ImportError:
    import hybridage2 as H
from sorties import SuiviExecution
from structures_communes import (POIDS_N2, InstanceNiveau2, ParametresHebergement, PoidsNiveau2, SolutionPatients,
                                 evaluer_niveau2, instance_niveau2_reference)


class C:
    """Outils (instances à capacités réduites, style des figures) : le script ne dépend d'aucun autre fichier."""

    @staticmethod
    def construire_instance(nom: str, lits: int, places: int) -> InstanceNiveau2:
        h = ParametresHebergement(lits_disponibles_par_jour=lits, places_ambulatoires_par_jour=places, reserve_lits=0)
        if nom == "etude":
            _, inst = instance_niveau2_reference()
        else:
            import planning_vacations_v28 as V28
            inst = V28.instance_niveau2(date(2026, 10, 12))
        base = InstanceNiveau2(inst.patients, inst.vacations, h, inst.noms_chirurgiens, f"{nom}_{lits}l_{places}p")
        return H.etendre_horizon(base, H.NB_SEMAINES_REPORT)

    @staticmethod
    def _plt():
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt

    @staticmethod
    def _style(ax, titre, xl="", yl=""):
        ax.set_title(titre, loc="left", fontsize=10, color="#22211e")
        ax.set_xlabel(xl, fontsize=8, color="#6b6a64")
        ax.set_ylabel(yl, fontsize=8, color="#6b6a64")
        ax.tick_params(colors="#6b6a64", labelsize=8)
        for c in ("top", "right"):
            ax.spines[c].set_visible(False)

POIDS = [  # (nom, libellé, valeur actuelle)
    ("non_place", "patient non placé", POIDS_N2.non_place),
    ("depassement_vac", "minute de dépassement", POIDS_N2.depassement_vac),
    ("bloc_inoccupe", "minute de bloc inoccupé", POIDS_N2.bloc_inoccupe),
    ("report", "semaine de report (x priorité)", H.PENALITE_SEMAINE_REPORT),
    ("lit", "lit-jour en trop", POIDS_N2.lit),
    ("var_lits", "variance des lits", POIDS_N2.var_lits),
    ("place", "place-jour en trop", POIDS_N2.place),
    ("var_places", "variance des places", POIDS_N2.var_places),
]
TOL_REPORTS, TOL_PRIO, TOL_OCC, MAX_DEP = 2.0, 2.0, 3.0, 60.0
VERT, ROUGE, ENCRE, ENCRE2, GRILLE = "#1baf7a", "#d62728", "#22211e", "#6b6a64", "#e4e3df"
COUL = {"etude": "#2a78d6", "v28": "#eb6834"}


class EtatTest(H.EtatAvecReport):
    def __init__(self, inst, aff, poids, report):
        super().__init__(inst, aff, penalite_semaine=report)
        self.poids = poids


class ProblemeTest(H.ProblemeHybrideN2):
    def __init__(self, inst, journal, poids, report):
        super().__init__(inst, journal)
        self.poids_test, self.report = poids, report

    def etat(self, ind):
        return EtatTest(self.inst, dict(zip(self.pids, ind)), self.poids_test, self.report)


_INST: dict = {}


def indicateurs(inst, aff) -> dict:
    V = inst.vacations
    ev = evaluer_niveau2(inst, SolutionPatients(aff))
    rep = [p for p, v in aff.items() if v is not None and V[v].semaine_decalage > 0]
    return {"non_places": ev.patients_non_places, "reportes": len(rep),
            "prio_reportes": sum(inst.patients[p].priorite >= 3 for p in rep),
            "occupation_pct": round(ev.taux_occupation_bloc_pct, 2),
            "vacations_vides": sum(1 for vid, v in V.items() if not v.supplementaire and vid not in set(aff.values())),
            "depassement_min": round(ev.depassement_bloc_minutes, 1),
            "debordement": ev.depassement_lits + ev.depassement_places,
            "lits_trop": ev.depassement_lits, "places_trop": ev.depassement_places}


def _essai(args) -> dict:
    nom, lits, places, poids_nom, facteur, graine, duree = args
    if (nom, lits, places) not in _INST:
        _INST[(nom, lits, places)] = C.construire_instance(nom, lits, places)
    inst = _INST[(nom, lits, places)]
    valeurs = {n: v for n, _, v in POIDS}
    valeurs[poids_nom] *= facteur
    report = valeurs.pop("report")
    pb = ProblemeTest(inst, H.Journal(SuiviExecution(pas_enregistrement=10 ** 9)), PoidsNiveau2(**valeurs), report)
    rng = random.Random(graine)
    depart = pb.depuis_solution(pb.solution_initiale(rng))
    ind, _ = H.RechercheLocaleMixte(2, pb, H.ParametresRechercheLocale()).tabou(depart, rng, duree=duree)
    return {"instance": nom, "poids": poids_nom, "facteur": facteur, "graine": graine,
            **indicateurs(inst, dict(zip(pb.pids, ind)))}


def analyser(essais, facteurs):
    """Moyennes (poids, facteur, instance) et viabilité de chaque (poids, facteur) sur TOUTES les instances."""
    moy = {}
    for e in essais:
        moy.setdefault((e["poids"], e["facteur"], e["instance"]), []).append(e)
    moy = {k: {c: statistics.fmean(x[c] for x in v) for c in v[0] if c not in ("instance", "poids", "graine")}
           for k, v in moy.items()}
    instances = sorted({k[2] for k in moy})

    def dur(m):                                           # règles strictes (planning réalisable)
        r = []
        if m["debordement"] > 0.5:
            r.append(f"{m['debordement']:.0f} lits/places-jours en trop")
        if m["non_places"] > 0.5:
            r.append(f"{m['non_places']:.0f} non placés")
        if m["depassement_min"] > MAX_DEP:
            r.append(f"{m['depassement_min']:.0f} min de dépassement (> {MAX_DEP:g})")
        return r

    ref = {i: [m for k, m in moy.items() if k[2] == i and not dur(m)] for i in instances}
    viable, motifs = {}, {}
    for n, _, _ in POIDS:
        for f in facteurs:
            raisons = []
            for i in instances:
                m = moy.get((n, f, i))
                if m is None:
                    continue
                raisons += [f"{i} : {x}" for x in dur(m)]
                # dominé : un autre planning réalisable fait nettement mieux sur les reports ET l'occupation
                dom = [o for o in ref[i] if o["reportes"] <= m["reportes"] - TOL_REPORTS
                       and o["occupation_pct"] >= m["occupation_pct"] + TOL_OCC
                       and o["prio_reportes"] <= m["prio_reportes"]]
                if dom:
                    o = min(dom, key=lambda x: x["reportes"])
                    raisons.append(f"{i} : dominé ({m['reportes']:.0f} reportés, {m['occupation_pct']:.0f} % "
                                   f"d'occupation, contre {o['reportes']:.0f} et {o['occupation_pct']:.0f} % possibles)")
                if m["prio_reportes"] > min((o["prio_reportes"] for o in ref[i]), default=0) + TOL_PRIO:
                    raisons.append(f"{i} : {m['prio_reportes']:.0f} patients prioritaires reportés")
            viable[(n, f)], motifs[(n, f)] = not raisons, raisons
    ref = {i: {"min_reportes": min((o["reportes"] for o in l), default=None),
               "max_occupation_pct": max((o["occupation_pct"] for o in l), default=None)} for i, l in ref.items()}
    return moy, instances, ref, viable, motifs


def plage(viable, n, facteurs):
    """Plus longue suite de facteurs viables contenant 1 (sinon la plus longue) -> (min, max) ou None."""
    suites, cur = [], []
    for f in facteurs:
        if viable[(n, f)]:
            cur.append(f)
        elif cur:
            suites.append(cur)
            cur = []
    if cur:
        suites.append(cur)
    if not suites:
        return None
    avec_1 = [s for s in suites if 1.0 in s]
    s = avec_1[0] if avec_1 else max(suites, key=len)
    return s[0], s[-1]


def figures(moy, instances, viable, facteurs, plages, recommande, sortie: Path):
    plt = C._plt()
    # 1. synthèse : plages viables
    fig, ax = plt.subplots(figsize=(11, 0.62 * len(POIDS) + 1.6))
    for k, (n, lib, v0) in enumerate(POIDS):
        y = len(POIDS) - 1 - k
        for f in facteurs:
            ax.scatter(f, y, s=40, color=VERT if viable[(n, f)] else ROUGE, marker="o" if viable[(n, f)] else "x",
                       zorder=3, lw=1.5)
        if plages[n]:
            ax.plot(plages[n], [y, y], color=VERT, lw=8, alpha=0.35, solid_capstyle="round", zorder=2)
        ax.scatter(1, y, s=170, facecolor="none", edgecolor=ENCRE, lw=2, zorder=4)
        r = recommande[n] / v0
        if abs(math.log(r)) > 1e-9:
            ax.scatter(r, y, s=170, marker="*", color="#eda100", zorder=5)
        ok = plages[n] is not None and plages[n][0] <= 1 <= plages[n][1]
        ax.text(facteurs[-1] * 1.8, y, ("✓ " if ok else "✗ ") + (f"{v0:g} justifié" if ok else
                f"{v0:g} -> {recommande[n]:g}"), va="center", fontsize=9, color=VERT if ok else ROUGE)
    ax.set_yticks(range(len(POIDS)), [f"{lib} ({v0:g})" for _, lib, v0 in reversed(POIDS)], fontsize=9)
    ax.set_xscale("log")
    ax.set_xticks(facteurs, [f"x{f:g}" for f in facteurs])
    ax.minorticks_off()
    ax.set_xlim(facteurs[0] / 2, facteurs[-1] * 12)
    ax.grid(axis="x", color=GRILLE)
    C._style(ax, "Plage où le planning reste viable quand on multiplie UN poids (les autres à leur valeur actuelle)\n"
                 "vert : viable ; croix rouge : non viable ; cercle : valeur actuelle ; étoile : valeur recommandée",
             "facteur appliqué au poids actuel (échelle log)")
    fig.tight_layout()
    fig.savefig(sortie / "plages_viables.png", dpi=150, facecolor="white")
    plt.close(fig)
    # 2. effets détaillés, par groupe
    indic = [("debordement", "lits + places-jours en trop"), ("reportes", "patients reportés"),
             ("occupation_pct", "occupation des vacations (%)"), ("depassement_min", "dépassement (min)")]
    for groupe, noms in (("bloc", POIDS[:4]), ("hebergement", POIDS[4:])):
        fig, axes = plt.subplots(len(noms), 4, figsize=(15, 2.7 * len(noms)), squeeze=False)
        for r, (n, lib, v0) in enumerate(noms):
            for c, (cle, titre) in enumerate(indic):
                ax = axes[r][c]
                for f0, f1 in zip(facteurs, facteurs[1:] + [facteurs[-1] * 1.0001]):
                    if viable[(n, f0)]:
                        ax.axvspan(f0 / 1.6, f0 * 1.6, color=VERT, alpha=0.10, lw=0)
                for i in instances:
                    xs = [f for f in facteurs if (n, f, i) in moy]
                    ax.plot(xs, [moy[(n, f, i)][cle] for f in xs], color=COUL.get(i, "#888"), lw=2, marker="o", ms=4,
                            label=i)
                ax.axvline(1, color=ENCRE, ls="--", lw=1)
                ax.set_xscale("log")
                ax.set_xticks(facteurs, [f"{f:g}" for f in facteurs], fontsize=7)
                ax.minorticks_off()
                ax.grid(color=GRILLE, lw=0.7)
                C._style(ax, titre if r == 0 else "", f"facteur sur « {lib} »" if r == len(noms) - 1 else "",
                         f"{lib}\n({v0:g})" if c == 0 else "")
        axes[0][0].legend(frameon=False, fontsize=8)
        fig.suptitle(f"Effet de chaque poids ({'bloc opératoire' if groupe == 'bloc' else 'hébergement'}) — bande verte : "
                     "planning viable ; pointillé : valeur actuelle", x=0.01, ha="left", fontsize=11, color=ENCRE)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        fig.savefig(sortie / f"effets_{groupe}.png", dpi=150, facecolor="white")
        plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Justification des points de pénalité (viabilité du planning)")
    ap.add_argument("--budget", type=float, default=300, help="secondes de calcul au total")
    ap.add_argument("--graines", type=int, default=2)
    ap.add_argument("--facteurs", type=float, nargs="+", default=[0.01, 0.1, 0.3, 1, 3, 10, 100])
    ap.add_argument("--lits", type=int, nargs=2, default=[10, 19])
    ap.add_argument("--places", type=int, nargs=2, default=[6, 6])
    ap.add_argument("--coeurs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--sortie", default="resultats_justification")
    o = ap.parse_args()
    sortie = Path(o.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    facteurs = sorted(set(o.facteurs) | {1.0})
    caps = {"etude": (o.lits[0], o.places[0]), "v28": (o.lits[1], o.places[1])}
    # le facteur 1 est le même planning pour tous les poids : calculé une fois, recopié ensuite
    configs = [("non_place", 1.0)] + [(n, f) for n, _, _ in POIDS for f in facteurs if f != 1.0]
    n = len(configs) * 2 * o.graines
    coeurs = max(1, o.coeurs)
    duree = max(0.5, 0.8 * o.budget * coeurs / n)
    print(f"{len(POIDS)} poids x {len(facteurs)} facteurs, 2 instances, {o.graines} graine(s) : {n} exécutions du Tabou "
          f"de {duree:.1f} s sur {coeurs} cœur(s) (≈ {n * duree / coeurs / 0.8 / 60:.1f} min)")
    taches = [(i, *caps[i], p, f, 1000 + g, duree) for i in caps for p, f in configs for g in range(o.graines)]
    t0 = time.perf_counter()
    with mp.Pool(coeurs) as pool:
        essais = list(pool.imap_unordered(_essai, taches))
    essais += [dict(e, poids=p) for e in essais if e["facteur"] == 1.0 for p, _, _ in POIDS if p != "non_place"]
    with (sortie / "essais.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(essais[0]), delimiter=";")
        w.writeheader()
        w.writerows(essais)

    moy, instances, ref, viable, motifs = analyser(essais, facteurs)
    plages = {n: plage(viable, n, facteurs) for n, _, _ in POIDS}
    recommande = {}
    for n, _, v0 in POIDS:
        p = plages[n]
        if p and p[0] <= 1 <= p[1]:
            recommande[n] = v0
        elif p:
            recommande[n] = round(v0 * math.sqrt(p[0] * p[1]), 3)
        else:
            recommande[n] = v0
    figures(moy, instances, viable, facteurs, plages, recommande, sortie)

    res = {"poids": {n: {"actuel": v0, "plage_viable": [v0 * p[0], v0 * p[1]] if (p := plages[n]) else None,
                         "justifie": bool(plages[n] and plages[n][0] <= 1 <= plages[n][1]), "recommande": recommande[n],
                         "pourquoi_non_viable": {f"x{f:g}": motifs[(n, f)] for f in facteurs if motifs[(n, f)]}}
                     for n, _, v0 in POIDS},
           "reference_meilleur_planning": ref, "tolerances": {"reports": TOL_REPORTS, "prioritaires": TOL_PRIO,
                                                               "occupation_points": TOL_OCC, "depassement_max_min": MAX_DEP},
           "temps_s": round(time.perf_counter() - t0)}
    (sortie / "poids_justifies.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 96)
    for n, lib, v0 in POIDS:
        p, ok = plages[n], res["poids"][n]["justifie"]
        txt = f"[{v0 * p[0]:g} ; {v0 * p[1]:g}]" if p else "aucune"
        print(f"  {lib:<32} actuel {v0:>7g}  plage viable {txt:<22} -> "
              + ("JUSTIFIÉ" if ok else f"À CHANGER : {recommande[n]:g}"))
        for f in (facteurs[0], facteurs[-1]):
            if motifs[(n, f)]:
                print(f"      x{f:g} : " + " ; ".join(motifs[(n, f)][:2]))
    print(f"  -> {sortie}/ ({time.perf_counter() - t0:.0f} s)")
    print("=" * 96)


if __name__ == "__main__":
    mp.freeze_support()
    main()