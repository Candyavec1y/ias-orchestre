# -*- coding: utf-8 -*-
"""
Figures ciblées (branche v3), calculées sur les mesures existantes, toutes méthodes incluses :
  * vitesse_convergence : meilleur score atteint au cours du temps (médiane des 10 graines, N1 et N2) et temps pour
    obtenir une première amélioration / atteindre son propre plateau -> rapidité de démarrage du Tabou ;
  * memetique_comparaisons : différences appariées par graine « memetique − autre méthode » sur l'objectif N2 (avec le
    nombre de graines gagnées et p de Wilcoxon), et réoptimisation globale du SMA par méthode.
Aucune valeur n'est modifiée : les figures montrent aussi les comparaisons défavorables (RS seul, AGS>RS>TABOU).
"""
from __future__ import annotations

import json
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import stats  # noqa: E402

from commun_rapport import (AGREGEES, COULEURS, MARQUEURS, METHODES, SORTIE, ecrire_csv,  # noqa: E402
                            lire_csv, sauver_figure)

SCRIPT = "scripts/l_figures_messages.py"
INSTANTS = np.geomspace(0.05, 10, 60)


def _meilleur_a(pts, t, depart):
    v = [s for (u, s) in pts if u <= t]
    return min(v) if v else depart


def vitesse(conv, depart_n2: float, depart_n1: float):
    lignes = []
    fig, axes = plt.subplots(1, 3, figsize=(17, 4.8), layout="constrained")
    for ax, (niv, camp, depart, titre) in zip(axes[:2], ((2, "N2_reference", depart_n2, "N2 v28 (objectif F2 + report)"),
                                                          (1, "N1", depart_n1, "N1 instance d'étude (F1)"))):
        for m in METHODES:
            cs = [c["convergence"] for c in conv if c["niveau"] == niv and c["campagne"] == camp and c["methode"] == m]
            med = [statistics.median(_meilleur_a(c, t, depart) for c in cs) for t in INSTANTS]
            ax.plot(INSTANTS, med, color=COULEURS[m], lw=3.0 if m == "TABOU seul" else 1.4,
                    marker=MARQUEURS[m], markevery=10, label=m)
            premiere = [next((u for u, s in c if s < depart - 1e-6), None) for c in cs]
            final = [min(s for _, s in c) if c else depart for c in cs]
            plateau = [next((u for u, s in c if s <= f + 0.01 * abs(f)), None) for c, f in zip(cs, final)]
            lignes.append({"niveau": niv, "methode": m,
                           "temps_premiere_amelioration_median_s": statistics.median([x for x in premiere if x is not None])
                           if any(x is not None for x in premiere) else None,
                           "temps_plateau_1pct_median_s": statistics.median([x for x in plateau if x is not None])
                           if any(x is not None for x in plateau) else None,
                           **{f"meilleur_median_{t}s": statistics.median(_meilleur_a(c, t, depart) for c in cs)
                              for t in (0.25, 0.5, 1, 2, 5, 10)}})
        ax.set(xscale="log", xlabel="Temps réel (s, échelle log)", ylabel="Meilleur score atteint (médiane, 10 graines)",
               title=titre)
        ax.axhline(depart, color="0.6", ls=":", lw=1)
        ax.text(0.055, depart, " départ", va="bottom", fontsize=8, color="0.4")
    axes[0].legend(fontsize=8)
    ax = axes[2]
    n2 = [l_ for l_ in lignes if l_["niveau"] == 2]
    x = np.arange(len(n2))
    ax.bar(x - 0.2, [l_["temps_premiere_amelioration_median_s"] or 0 for l_ in n2], 0.4,
           color=[COULEURS[l_["methode"]] for l_ in n2], edgecolor="k", label="première amélioration du départ")
    ax.bar(x + 0.2, [l_["temps_plateau_1pct_median_s"] or 0 for l_ in n2], 0.4, color="white",
           edgecolor=[COULEURS[l_["methode"]] for l_ in n2], hatch="//", label="à 1 % de son meilleur score final")
    ax.set_xticks(x, [l_["methode"] for l_ in n2], rotation=25, fontsize=8)
    ax.set(ylabel="Temps réel médian (s)", title="N2 : délai de démarrage et de convergence")
    ax.legend(fontsize=8)
    fig.suptitle("Rapidité : le Tabou (trait épais) est la première méthode à améliorer le départ ; "
                 "il plafonne ensuite à un niveau moins bon")
    figs = sauver_figure(fig, "vitesse_convergence")
    plt.close(fig)
    ecrire_csv(AGREGEES / "vitesse_convergence.csv", lignes)
    return figs, lignes


def comparaisons_memetique():
    ref = [l_ for l_ in lire_csv(SORTIE / "n2_resultats.csv") if l_["campagne"] == "N2_reference"]
    obj = {(l_["methode"], int(l_["graine"])): float(l_["score_recherche"]) for l_ in ref if l_["faisable"] == "True"}
    autres = ["AGS seul", "TABOU seul", "RS>AGS>TABOU", "AGS>RS>TABOU", "RS seul"]
    holm = {r["comparaison"]: r for r in lire_csv(AGREGEES / "n2_tests_confirmatoires.csv") if r["critere"] == "score_recherche"}
    fig, axes = plt.subplots(1, 2, figsize=(15, 5), layout="constrained")
    ax = axes[0]
    res = []
    for k, m in enumerate(autres):
        g = sorted(gr for (mm, gr) in obj if mm == "memetique" and ("memetique", gr) in obj and (m, gr) in obj)
        d = [obj[("memetique", gr)] - obj[(m, gr)] for gr in g]
        p = stats.wilcoxon([obj[("memetique", gr)] for gr in g], [obj[(m, gr)] for gr in g]).pvalue if any(d) else 1.0
        gagne = sum(x < 0 for x in d)
        couleur = "tab:green" if np.median(d) < 0 else "tab:red"
        ax.scatter(d, np.full(len(d), k), color=couleur, s=30, zorder=3)
        ax.plot([np.median(d)] * 2, [k - 0.3, k + 0.3], color="k", lw=2)
        info = holm.get(f"memetique - {m}")
        ptxt = f"p Holm = {float(info['p_holm']):.3f}" if info and info.get("p_holm") else f"p = {p:.3f} (exploratoire)"
        ax.text(ax.get_xlim()[1] if False else 0, k + 0.33, f"memetique gagne {gagne}/{len(d)} graines ; {ptxt}",
                fontsize=8, ha="center")
        res.append({"contre": m, "paires": len(d), "memetique_gagne": gagne, "difference_mediane": float(np.median(d)),
                    "p": p})
    ax.axvline(0, color="0.4", ls="--")
    ax.set_yticks(range(len(autres)), [f"contre {m}" for m in autres])
    ax.set(xlabel="Objectif memetique − objectif de l'autre méthode, même graine (négatif = memetique meilleur)",
           title="N2 v28, cohorte de référence, 10 s : memetique bat TABOU seul et AGS seul,\npas RS seul ni AGS>RS>TABOU")
    ax = axes[1]
    sma = lire_csv(AGREGEES / "v3_pilote" / "sma_reoptimisation_globale.csv")
    etiquettes = {"S_CN": "aucune\n(site)", "G_memetique": "memetique", "G_AGS>RS>TABOU": "AGS>RS>TABOU", "G_RS": "RS seul"}
    couleurs = {"S_CN": "0.7", "G_memetique": COULEURS["memetique"], "G_AGS>RS>TABOU": COULEURS["AGS>RS>TABOU"],
                "G_RS": COULEURS["RS seul"]}
    for k, s in enumerate(etiquettes):
        ls = [l_ for l_ in sma if l_["strategie"] == s]
        score = sum(float(l_["score_programme"]) for l_ in ls)
        appl = sum(float(l_["reoptimisations_appliquees"] or 0) for l_ in ls)
        calc = sum(float(l_["reoptimisations_globales"] or 0) for l_ in ls)
        ax.bar(k, score, color=couleurs[s], edgecolor="k")
        ax.text(k, score, f"{score:,.0f}".replace(",", " ") + (f"\n{appl:.0f}/{calc:.0f} plans appliqués" if calc else ""),
                ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(etiquettes)), list(etiquettes.values()))
    ax.set(ylabel="Score cumulé du programme, 21 scénarios (à minimiser)",
           title="SMA, réoptimisation globale (1 s) : memetique donne le meilleur programme")
    ax.set_ylim(0, max(p.get_height() for p in ax.patches) * 1.15)
    figs = sauver_figure(fig, "memetique_comparaisons")
    plt.close(fig)
    ecrire_csv(AGREGEES / "memetique_comparaisons.csv", res)
    return figs


def main():
    conv = json.loads((AGREGEES / "convergence.json").read_text(encoding="utf-8"))
    n2 = lire_csv(SORTIE / "n2_resultats.csv")
    depart_n2 = next(float(l_["score_recherche"]) for l_ in n2 if l_["campagne"] == "N2_reference" and l_["methode"] == "glouton")
    depart_n1 = next(float(l_["score_depart"]) for l_ in lire_csv(SORTIE / "n1_resultats.csv"))
    _, lignes = vitesse(conv, depart_n2, depart_n1)
    comparaisons_memetique()
    for l_ in lignes:
        print(l_["niveau"], l_["methode"], l_["temps_premiere_amelioration_median_s"], l_["temps_plateau_1pct_median_s"])


if __name__ == "__main__":
    main()
