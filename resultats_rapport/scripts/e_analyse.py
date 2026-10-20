# -*- coding: utf-8 -*-
"""
Analyse des campagnes D (N1) et E (N2) : résumés statistiques, test confirmatoire fixé a priori
(PREPARATION_EXPERIENCES.md), gains et contreparties, figures F2-F5 et F7. Lit uniquement les sorties agrégées.

Règle de l'équipe : pendant la recherche, les dépassements sont seulement
pénalisés ; à la fin, SEULES les solutions faisables sont proposées (contrainte dure). Une exécution dont la
solution finale n'est pas faisable compte donc comme « aucune solution proposée » : elle entre dans le taux de
solutions proposées, mais pas dans les statistiques de qualité. Le glouton est le DÉPART commun (référence), décrit
sur toutes ses exécutions.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import stats  # noqa: E402

from commun_rapport import (AGREGEES, COULEURS, MARQUEURS, METHODES, SORTIE, ecrire_csv,  # noqa: E402
                            lire_csv, resume_stat, sauver_figure)

SCRIPT = "scripts/e_analyse.py"
ORDRE = ["glouton", "premier créneau"] + METHODES


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _vrai(x) -> bool:
    return str(x) == "True"


def charger():
    n1 = lire_csv(SORTIE / "n1_resultats.csv")
    n2 = lire_csv(SORTIE / "n2_resultats.csv")
    conv = json.loads((AGREGEES / "convergence.json").read_text(encoding="utf-8"))
    sols = json.loads((AGREGEES / "solutions_synthetiques.json").read_text(encoding="utf-8"))
    return n1, n2, conv, sols


def _gain(depart, final):
    return 100 * (depart - final) / depart if depart else None


def resume(lignes, cles, metriques):
    groupes = defaultdict(list)
    for l_ in lignes:
        groupes[tuple(l_.get(k, "") for k in cles)].append(l_)
    out = []
    for g, ls in sorted(groupes.items(), key=lambda kv: (kv[0][:-1], ORDRE.index(kv[0][-1]) if kv[0][-1] in ORDRE else 99)):
        ligne = dict(zip(cles, g))
        proposees = ls if g[-1] == "glouton" else [l_ for l_ in ls if _vrai(l_["faisable"])]
        ligne["executions"] = len(ls)
        ligne["solutions_proposees"] = len(proposees) if g[-1] != "glouton" else "départ"
        ligne["taux_faisable_pct"] = 100 * sum(_vrai(l_["faisable"]) for l_ in ls) / len(ls)
        if "faisable_strict" in ls[0]:                    # N2 : faisables seulement grâce à la tolérance
            ligne["proposees_grace_tolerance"] = sum(_vrai(l_["faisable"]) and not _vrai(l_["faisable_strict"]) for l_ in ls)
        for m in metriques:
            s = resume_stat([_f(l_.get(m)) for l_ in proposees])
            for k, v in s.items():
                if k != "n":
                    ligne[f"{m}_{k}"] = v
        out.append(ligne)
    return out


def analyse_n1(n1, conv, sols):
    for l_ in n1:
        l_["gain_vs_depart_pct"] = _gain(_f(l_["score_depart"]), _f(l_["score_commun"]))
    best = min(_f(l_["score_commun"]) for l_ in n1 if _vrai(l_["faisable"]))
    for l_ in n1:
        l_["ecart_meilleur_observe_pct"] = 100 * (_f(l_["score_commun"]) - best) / abs(best) if best else None
    met = ["score_commun", "gain_vs_depart_pct", "ecart_meilleur_observe_pct", "conflits_salles",
           "conflits_chirurgiens", "salles_differentes", "fragmentation", "blocs_places", "vacations",
           "temps_reel_s", "evaluations"]
    res = resume(n1, ["methode"], met)
    ecrire_csv(SORTIE / "n1_resume.csv", res)

    fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
    meth = [m for m in ORDRE if any(l_["methode"] == m for l_ in n1)]
    for k, m in enumerate(meth):
        v = [_f(l_["score_commun"]) for l_ in n1 if l_["methode"] == m]
        ax.boxplot([v], positions=[k], widths=0.6, patch_artist=True,
                   boxprops=dict(facecolor=COULEURS[m], alpha=0.5), medianprops=dict(color="k"), showfliers=False)
        ax.scatter(np.full(len(v), k) + np.linspace(-0.15, 0.15, len(v)), v, c="k", s=10, marker=MARQUEURS[m])
    ax.set_xticks(range(len(meth)), meth, rotation=20)
    ax.set(ylabel="F1 commun (à minimiser)", title=f"N1, instance d'étude fictive : 10 graines, budget 10 s "
                                                     f"(toutes les solutions sont faisables : {all(_vrai(l_['faisable']) for l_ in n1)})")
    sauver_figure(fig, "n1_scores")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for m in METHODES:
        for c in [c for c in conv if c["niveau"] == 1 and c["methode"] == m]:
            pts = c["convergence"]
            if pts:
                ax.step([p[0] for p in pts] + [10], [p[1] for p in pts] + [pts[-1][1]], where="post",
                        color=COULEURS[m], alpha=0.35, lw=1)
        ax.plot([], [], color=COULEURS[m], label=m)
    ax.set(xlabel="Temps réel (s)", ylabel="Meilleur F1 trouvé", title="N1 : convergence (10 graines par méthode)")
    ax.legend(fontsize=8)
    sauver_figure(fig, "n1_convergence")
    plt.close(fig)

    # Gantt d'une solution faisable de meilleur score (méthode / graine indiquées)
    import hybridation as H
    inst1 = H.charger_instances("etude")[0]
    meil = min((l_ for l_ in n1 if _vrai(l_["faisable"])), key=lambda l_: (_f(l_["score_commun"]), l_["methode"]))
    sol = next(s["solution"] for s in sols if s["niveau"] == 1 and s["methode"] == meil["methode"]
               and int(s["graine"]) == int(meil["graine"]))
    jours = sorted({c.jour for c in inst1.creneaux.values()})
    fig, axes = plt.subplots(1, len(jours), figsize=(15, 3.6), sharey=True, layout="constrained")
    cmap = plt.get_cmap("tab10")
    for bloc, plage in sol.items():
        pl = inst1.plages_bloc[plage]
        c = inst1.creneaux[pl.creneau_id]
        chir = inst1.blocs_a_placer[int(bloc)].chirurgien_id
        ax = axes[jours.index(c.jour)]
        d0 = c.heure_debut.hour + c.heure_debut.minute / 60
        d1 = c.heure_fin.hour + c.heure_fin.minute / 60
        ax.barh(pl.salle_id, d1 - d0, left=d0, color=cmap(chir % 10), edgecolor="k")
        ax.text((d0 + d1) / 2, pl.salle_id, inst1.chirurgiens[chir].nom.replace("Dr ", ""), ha="center", va="center", fontsize=8)
    for p in inst1.plages_bloc.values():
        if p.type_plage == "URGENCE":
            c = inst1.creneaux[p.creneau_id]
            axes[jours.index(c.jour)].barh(p.salle_id, 2, left=c.heure_debut.hour, color="none", hatch="///", edgecolor="r")
    for ax, j in zip(axes, jours):
        ax.set(title=f"{['Lun', 'Mar', 'Mer', 'Jeu', 'Ven'][j.weekday()]} {j:%d/%m}", xlim=(8, 17), xticks=[8, 10, 12, 13, 15, 17])
    axes[0].set(yticks=sorted(inst1.salles), yticklabels=[f"Salle {s}" for s in sorted(inst1.salles)])
    fig.suptitle(f"N1 : planning faisable de meilleur F1 ({meil['methode']}, graine {meil['graine']}, "
                 f"F1 = {_f(meil['score_commun']):.0f}) ; hachures rouges : plages réservées aux urgences")
    sauver_figure(fig, "n1_gantt")
    plt.close(fig)
    return res


def analyse_n2(n2, conv):
    """Classement et résumés sur le critère OPTIMISÉ par les méthodes : score_recherche = F2 commun + pénalité de
    report (« objectif ») ; F2 commun et ses composantes sont publiés à côté."""
    depart_obj = {(l_["charge_pct"], l_["cohorte"]): _f(l_["score_recherche"]) for l_ in n2 if l_["methode"] == "glouton"}
    for l_ in n2:
        l_["gain_vs_depart_pct"] = _gain(depart_obj.get((l_["charge_pct"], l_["cohorte"])), _f(l_["score_recherche"]))
        l_["gain_f2_vs_depart_pct"] = _gain(_f(l_["score_depart"]), _f(l_["score_commun"]))
        l_["grace_tolerance"] = int(_vrai(l_["faisable"]) and not _vrai(l_.get("faisable_strict", l_["faisable"])))
    ref = [l_ for l_ in n2 if l_["campagne"] == "N2_reference"]
    # écart à la meilleure solution FAISABLE observée sur la même instance (budget 10 s), sur l'objectif et sur F2
    par_inst = defaultdict(list)
    for l_ in n2:
        if l_["campagne"] != "N2_budgets":
            par_inst[(l_["charge_pct"], l_["cohorte"])].append(l_)
    for ls in par_inst.values():
        for cle, sortie in (("score_recherche", "ecart_meilleur_faisable_pct"), ("score_commun", "ecart_meilleur_faisable_f2_pct")):
            faisables = [_f(l_[cle]) for l_ in ls if _vrai(l_["faisable"])]
            best = min(faisables) if faisables else None
            for l_ in ls:
                l_[sortie] = (100 * (_f(l_[cle]) - best) / abs(best)) if best else None
    met = ["score_recherche", "score_commun", "penalite_report", "score_bloc", "score_lits", "score_places",
           "gain_vs_depart_pct", "gain_f2_vs_depart_pct", "ecart_meilleur_faisable_pct",
           "ecart_meilleur_faisable_f2_pct", "non_places", "patients_reportes",
           "semaines_report_total", "delai_moyen_j", "delai_max_j", "delai_moyen_j_p4", "delai_moyen_j_p1",
           "taux_occupation_bloc_pct", "temps_inoccupe_min", "depassement_bloc_min", "vacations_vides",
           "pic_lits", "jours_lits_pleins", "taux_occupation_lits_pct", "pic_places", "jours_places_pleines",
           "taux_occupation_places_pct", "nb_violations", "temps_reel_s", "evaluations"]
    res_ref = resume(ref, ["campagne", "methode"], met)
    # charges : 100 % = cohorte de référence (graines 1-3) + cohortes 44 et 45
    charges = [l_ for l_ in n2 if l_["campagne"] == "N2_charges"] + \
              [l_ for l_ in ref if int(l_["graine"]) <= 3]
    res_ch = resume(charges, ["charge_pct", "methode"], met)
    budgets = [l_ for l_ in n2 if l_["campagne"] == "N2_budgets"] + \
              [l_ for l_ in ref if int(l_["graine"]) <= 3 and l_["methode"] in METHODES]
    res_b = resume(budgets, ["budget_s", "methode"], ["score_recherche", "score_commun", "temps_reel_s", "evaluations"])
    ecrire_csv(SORTIE / "n2_resume.csv", [dict(groupe="reference", **r) for r in res_ref]
               + [dict(groupe="charges", **r) for r in res_ch] + [dict(groupe="budgets", **r) for r in res_b])

    # --- tests appariés par graine (solutions proposées), sur l'objectif puis sur F2 commun ---
    # famille confirmatoire (fixée a priori, Holm) : memetique contre chaque méthode seule ; exploratoire :
    # AGS>RS>TABOU (hybridation de référence retenue après le pilote) contre RS seul
    def apparie(m1, m2, cle):
        a = {int(l_["graine"]): _f(l_[cle]) for l_ in ref if l_["methode"] == m1 and _vrai(l_["faisable"])}
        b = {int(l_["graine"]): _f(l_[cle]) for l_ in ref if l_["methode"] == m2 and _vrai(l_["faisable"])}
        g = sorted(set(a) & set(b))
        d = [a[k] - b[k] for k in g]
        w = stats.wilcoxon([a[k] for k in g], [b[k] for k in g]) if any(d) else None
        return {"comparaison": f"{m1} - {m2}", "critere": cle, "n_paires": len(g),
                "difference_mediane": float(np.median(d)) if d else None, "difference_moyenne": float(np.mean(d)) if d else None,
                "premiere_meilleure": sum(x < 0 for x in d), "statistique_W": w.statistic if w else None,
                "p_brute": w.pvalue if w else 1.0}
    tests = []
    for cle in ("score_recherche", "score_commun"):
        famille = [apparie("memetique", m, cle) for m in ("RS seul", "TABOU seul", "AGS seul")]
        ordre = sorted(range(len(famille)), key=lambda i: famille[i]["p_brute"])
        pmax = 0.0
        for rang, i in enumerate(ordre):
            pmax = max(pmax, min(1.0, famille[i]["p_brute"] * (len(famille) - rang)))
            famille[i].update(p_holm=pmax, significatif_5pct=pmax < 0.05, statut="confirmatoire")
        expl = apparie("AGS>RS>TABOU", "RS seul", cle)
        expl.update(p_holm=None, significatif_5pct=expl["p_brute"] < 0.05, statut="exploratoire")
        tests += famille + [expl]
    ecrire_csv(AGREGEES / "n2_tests_confirmatoires.csv", tests)

    # --- gains et contreparties (cohorte de référence, moyennes sur les graines) ---
    gc = []
    for r in res_ref:
        gc.append({"methode": r["methode"], "executions": r["executions"], "solutions_proposees": r["solutions_proposees"],
                   "taux_faisable_pct": r["taux_faisable_pct"],
                   "proposees_grace_tolerance": r.get("proposees_grace_tolerance"),
                   **{k: r.get(f"{k}_moyenne") for k in ("score_recherche", "score_commun", "gain_vs_depart_pct",
                                                         "score_bloc", "score_lits", "score_places", "penalite_report", "taux_occupation_bloc_pct", "temps_inoccupe_min",
                                                         "pic_lits", "jours_lits_pleins", "pic_places",
                                                         "jours_places_pleines", "patients_reportes",
                                                         "semaines_report_total", "delai_moyen_j", "delai_moyen_j_p4",
                                                         "temps_reel_s")}})
    ecrire_csv(SORTIE / "gains_contreparties.csv", gc)

    figs = []
    # F3 scores (référence)
    fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained")
    meth = [m for m in ORDRE if any(l_["methode"] == m for l_ in ref)]
    etiquettes = []
    for k, m in enumerate(meth):
        ls = [l_ for l_ in ref if l_["methode"] == m]
        if m == "glouton":                           # départ commun : affiché pour référence, non proposé
            ax.scatter([k], [_f(ls[0]["score_recherche"])], facecolors="none", edgecolors="r", s=40, marker="o")
            etiquettes.append("départ\n(non faisable)" if not _vrai(ls[0]["faisable"]) else "départ")
            continue
        v = [_f(l_["score_recherche"]) for l_ in ls if _vrai(l_["faisable"])]
        if v:
            ax.boxplot([v], positions=[k], widths=0.6, patch_artist=True,
                       boxprops=dict(facecolor=COULEURS[m], alpha=0.5), medianprops=dict(color="k"), showfliers=False)
            ax.scatter(np.full(len(v), k) + np.linspace(-0.15, 0.15, len(v)), v, c="k", s=14, marker="o")
        etiquettes.append(f"{m}\n{len(v)}/{len(ls)} proposées")
    ax.set_xticks(range(len(meth)), etiquettes, rotation=20, fontsize=8)
    ax.set(ylabel="Objectif F2 + report des solutions proposées (à minimiser)",
           title="N2 v28, cohorte de référence (charge 100 %) : 10 graines, budget 10 s ; "
                 "seules les solutions faisables sont proposées")
    figs += sauver_figure(fig, "n2_scores")
    plt.close(fig)

    # F4a composantes
    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    larg = 0.2
    for i, comp in enumerate(("score_bloc", "score_lits", "score_places", "penalite_report")):
        moy = [next(r for r in res_ref if r["methode"] == m).get(f"{comp}_moyenne") or 0 for m in meth]
        et = [next(r for r in res_ref if r["methode"] == m).get(f"{comp}_ecart_type") or 0 for m in meth]
        ax.bar(np.arange(len(meth)) + (i - 1.5) * larg, moy, larg, yerr=et, capsize=2,
               label={"score_bloc": "bloc", "score_lits": "lits", "score_places": "places",
                      "penalite_report": "report"}[comp], color=["0.2", "0.5", "0.75", "0.95"][i], edgecolor="k")
    ax.set_xticks(range(len(meth)), meth, rotation=20)
    ax.set(ylabel="Composante pondérée (moyenne ± écart-type)",
           title="N2 référence : composantes de l'objectif (F2 = bloc + lits + places ; + report)")
    ax.legend()
    figs += sauver_figure(fig, "n2_composantes")
    plt.close(fig)

    # F4b qualité vs budget
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for m in METHODES:
        pts = sorted((float(r["budget_s"]), r.get("score_recherche_moyenne", math.nan), r.get("score_recherche_ecart_type", 0.0),
                      r["taux_faisable_pct"]) for r in res_b if r["methode"] == m)        # NaN : aucune solution proposée
        ax.errorbar([p[0] for p in pts], [p[1] for p in pts], yerr=[p[2] for p in pts], color=COULEURS[m],
                    marker=MARQUEURS[m], capsize=3, label=m)
    ax.set(xscale="log", xticks=[2, 5, 10, 20], xticklabels=["2", "5", "10", "20"], xlabel="Budget (s, temps réel)",
           ylabel="Objectif F2 + report des solutions proposées (moy. ± é.-t.)",
           title="N2 référence : qualité selon le budget (point absent : aucune solution proposée)")
    ax.legend(fontsize=8)
    figs += sauver_figure(fig, "n2_qualite_budget")
    plt.close(fig)

    # F5 convergence (score de RECHERCHE, seul enregistré au fil de l'exécution)
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for m in METHODES:
        for c in [c for c in conv if c["niveau"] == 2 and c["campagne"] == "N2_reference" and c["methode"] == m]:
            pts = c["convergence"]
            if pts:
                ax.step([p[0] for p in pts] + [10], [p[1] for p in pts] + [pts[-1][1]], where="post",
                        color=COULEURS[m], alpha=0.35, lw=1)
        ax.plot([], [], color=COULEURS[m], label=m)
    ax.set(xlabel="Temps réel (s)", ylabel="Meilleur score de recherche (F2 + report)",
           title="N2 référence : convergence (10 graines par méthode)")
    ax.legend(fontsize=8)
    figs += sauver_figure(fig, "n2_convergence")
    plt.close(fig)

    # F7 faisabilité et score selon la charge
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), layout="constrained")
    for m in ORDRE:
        pts = sorted((int(r["charge_pct"]), r["taux_faisable_pct"], r.get("non_places_moyenne"), r.get("patients_reportes_moyenne"))
                     for r in res_ch if r["methode"] == m)
        if not pts:
            continue
        axes[0].plot([p[0] for p in pts], [p[1] for p in pts], marker=MARQUEURS[m], color=COULEURS[m], label=m)
        axes[1].plot([p[0] for p in pts], [p[3] for p in pts], marker=MARQUEURS[m], color=COULEURS[m], label=m)
    axes[0].set(xlabel="Charge (% de la capacité utile visée)", ylabel="Exécutions avec une solution proposée (%)",
                title="Solutions proposées (faisables), 3 cohortes × 3 graines")
    axes[1].set(xlabel="Charge (% de la capacité utile visée)", ylabel="Patients reportés (moyenne)",
                title="Patients reportés après l'horizon (solutions proposées)")
    axes[0].legend(fontsize=8)
    figs += sauver_figure(fig, "n2_charges")
    plt.close(fig)

    # délai par priorité
    fig, ax = plt.subplots(figsize=(10, 4.5), layout="constrained")
    for i, prio in enumerate((1, 2, 3, 4)):
        moy = [resume_stat([_f(l_.get(f"delai_moyen_j_p{prio}")) for l_ in ref if l_["methode"] == m
                            and (m == "glouton" or _vrai(l_["faisable"]))]).get("moyenne") or 0
               for m in meth]
        ax.bar(np.arange(len(meth)) + (i - 1.5) * 0.2, moy, 0.2, label=f"priorité {prio}",
               color=["0.85", "0.6", "0.35", "0.1"][i], edgecolor="k")
    ax.set_xticks(range(len(meth)), meth, rotation=20)
    ax.set(ylabel="Délai moyen date au plus tôt → intervention (jours)", title="N2 référence : délai par priorité (solutions proposées ; glouton = départ)")
    ax.legend()
    figs += sauver_figure(fig, "n2_delai_priorite")
    plt.close(fig)
    return res_ref, tests


if __name__ == "__main__":
    n1, n2, conv, sols = charger()
    analyse_n1(n1, conv, sols)
    r, t = analyse_n2(n2, conv)
    for x in t:
        print(x)
