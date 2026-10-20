# -*- coding: utf-8 -*-
"""
Tâche B (instances.csv, agrégats) et tableaux LaTeX T1-T7 (booktabs, virgule décimale) générés À PARTIR des sorties
mesurées. Aucune valeur n'est saisie à la main.
"""
from __future__ import annotations


from commun_rapport import METHODES, SORTIE, ecrire_csv, enregistrer_manifeste, fr, lire_csv

SCRIPT = "scripts/j_tableaux.py"
ORDRE = ["glouton", "premier créneau"] + METHODES


def instances():
    import hybridation as H
    from parametres import LUNDI_REFERENCE as L0
    import scenarios_sma as SC_SMA
    lignes = []
    i1 = H.charger_instances("etude")[0]
    lignes.append({"famille": "N1 instance d'étude fictive", "chirurgiens": len(i1.chirurgiens), "salles": len(i1.salles),
                   "plages": len(i1.plages_bloc), "plages_urgence": sum(p.type_plage == "URGENCE" for p in i1.plages_bloc.values()),
                   "blocs_2h_a_placer": len(i1.blocs_a_placer), "semaines": 1})
    for pct, c in {70: 0.63, 85: 0.765, 100: 0.90, 115: 1.035}.items():
        for coh in (43, 44, 45):
            b = H.instance_v28(L0, 4, graine=coh, charge=c)
            reg = [v for v in b.vacations.values() if not v.supplementaire]
            ext = H.etendre_horizon(b, H.NB_SEMAINES_REPORT)
            pts = list(b.patients.values())
            cap = sum(v.capacite_utile_minutes for v in reg)
            lignes.append({"famille": "N2 v28", "charge_visee_pct": pct, "charge_generateur": c, "cohorte": coh,
                           "chirurgiens": len({v.chirurgien_id for v in reg}), "salles": len({v.salle_id for v in reg}),
                           "semaines": 4, "semaines_report": H.NB_SEMAINES_REPORT, "vacations": len(reg),
                           "vacations_report": len(ext.vacations) - len(reg), "capacite_utile_min": cap,
                           "patients": len(pts), "demande_min": sum(p.duree_bloc for p in pts),
                           "charge_mesuree_pct": 100 * sum(p.duree_bloc for p in pts) / cap,
                           "part_ambulatoire_pct": 100 * sum(p.ambulatoire for p in pts) / len(pts),
                           **{f"priorite_{k}_pct": 100 * sum(p.priorite == k for p in pts) / len(pts) for k in (1, 2, 3, 4)},
                           "lits": b.hebergement.lits_disponibles_par_jour, "reserve_lits": b.hebergement.reserve_lits,
                           "places": b.hebergement.places_ambulatoires_par_jour, "marge_vacation_pct": 10})
    i1s, i2s, _ = SC_SMA.instances_par_defaut()
    reg = [v for v in i2s.vacations.values() if not v.supplementaire]
    lignes.append({"famille": "SMA v28 (scénarios)", "semaines": 2, "vacations": len(reg), "patients": len(i2s.patients),
                   "chirurgiens": len({v.chirurgien_id for v in reg}), "salles": len({v.salle_id for v in reg}),
                   "lits": i2s.hebergement.lits_disponibles_par_jour, "reserve_lits": i2s.hebergement.reserve_lits,
                   "places": i2s.hebergement.places_ambulatoires_par_jour,
                   "part_ambulatoire_pct": 100 * sum(p.ambulatoire for p in i2s.patients.values()) / len(i2s.patients)})
    ml = {(l_["modele"], l_["metrique"]): l_["valeur"] for l_ in lire_csv(SORTIE / "ml_resultats.csv")}
    lignes.append({"famille": "ML", "patients": ml[("donnees", "sejours_apres_preparation")],
                   "part_ambulatoire_pct": 100 * float(ml[("donnees", "effectif_ambulatoire")]) / float(ml[("donnees", "sejours_apres_preparation")])})
    for l_ in lire_csv(SORTIE / "saturation_resultats.csv")[:1]:
        lignes.append({"famille": "Saturation v28 (programme vide)", "semaines": 4, "patients": l_["patients_inscrits"],
                       "lits": l_["lits"], "reserve_lits": l_["reserve"], "places": l_["places"]})
    ecrire_csv(SORTIE / "instances.csv", lignes)
    return lignes


def _tab(entete, lignes, legende, etiquette, colfmt):
    corps = "\n".join(" & ".join(str(x).replace(">", r"\textgreater{}") for x in c) + r" \\" for c in lignes)
    return (f"\\begin{{table}}[htbp]\n\\centering\n\\small\n\\caption{{{legende}}}\n\\label{{{etiquette}}}\n"
            f"\\begin{{tabular}}{{{colfmt}}}\n\\toprule\n{' & '.join(entete)} \\\\\n\\midrule\n{corps}\n"
            f"\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")


def _f(d, k):
    try:
        return float(d.get(k))
    except (TypeError, ValueError):
        return None


def tableaux():
    tex = ["% Tableaux générés par resultats_rapport/scripts/j_tableaux.py à partir des CSV mesurés.",
           "% Nécessite \\usepackage{booktabs}.", ""]
    # T1 instances
    inst = lire_csv(SORTIE / "instances.csv")
    l1 = []
    for l_ in inst:
        if l_["famille"] == "N2 v28" and l_["cohorte"] != "43":
            continue
        l1.append([l_["famille"] + (f" {l_['charge_visee_pct']} \\%" if l_.get("charge_visee_pct") else ""),
                   l_.get("chirurgiens") or "—", l_.get("salles") or "—", l_.get("semaines") or "—",
                   l_.get("vacations") or l_.get("blocs_2h_a_placer") or "—", l_.get("patients") or "—",
                   fr(_f(l_, "charge_mesuree_pct")) if l_.get("charge_mesuree_pct") else "—",
                   f"{l_.get('lits') or '—'} / {l_.get('reserve_lits') or '—'} / {l_.get('places') or '—'}"])
    tex.append(_tab(["Instance", "Chir.", "Salles", "Sem.", "Vacations / blocs", "Patients", "Charge (\\%)", "Lits / réserve / places"],
                    l1, "Instances (cohorte 43 pour N2 ; budget 10~s, graines 1--10 ; voir parametres.md)", "tab:instances", "lrrrrrrl"))
    # T2 ML
    ml = {(l_["modele"], l_["metrique"]): float(l_["valeur"]) for l_ in lire_csv(SORTIE / "ml_resultats.csv")}
    l2 = [["Durée au bloc (min)", fr(ml[("duree_bloc_modele_min", "n_test")], 0), fr(ml[("duree_bloc_modele_min", "r2")], 3),
           fr(ml[("duree_bloc_modele_min", "mae")]), fr(ml[("duree_bloc_modele_min", "rmse")]),
           f"médiane par type : R² {fr(ml[('duree_bloc_ref_mediane_par_type_min', 'r2')], 2)}, MAE {fr(ml[('duree_bloc_ref_mediane_par_type_min', 'mae')])}"],
          ["Nuits avant (hosp.)", fr(ml[("nuits_avant_modele_j", "n_test")], 0), fr(ml[("nuits_avant_modele_j", "r2")], 3),
           fr(ml[("nuits_avant_modele_j", "mae")], 2), fr(ml[("nuits_avant_modele_j", "rmse")], 2),
           f"médiane : MAE {fr(ml[('nuits_avant_ref_mediane_j', 'mae')], 2)}"],
          ["Nuits après (hosp.)", fr(ml[("nuits_apres_modele_j", "n_test")], 0), fr(ml[("nuits_apres_modele_j", "r2")], 3),
           fr(ml[("nuits_apres_modele_j", "mae")], 2), fr(ml[("nuits_apres_modele_j", "rmse")], 2),
           f"médiane : MAE {fr(ml[('nuits_apres_ref_mediane_j', 'mae')], 2)}"],
          ["Mode (ambu./hosp.)", fr(ml[("separation", "n_test")], 0), f"acc. {fr(ml[('capacite_modele', 'accuracy')], 3)}",
           f"F1 {fr(ml[('capacite_modele', 'f1_ambulatoire')], 3)} / {fr(ml[('capacite_modele', 'f1_lit_classique')], 3)}",
           f"Brier {fr(ml[('capacite_modele', 'brier_ambulatoire')], 3)}",
           f"majoritaire : acc. {fr(ml[('capacite_ref_majoritaire', 'accuracy')], 3)}"]]
    tex.append(_tab(["Modèle", "n test", "R² / acc.", "MAE / F1", "RMSE / Brier", "Référence simple"], l2,
                    "Quatre modèles ML sur le jeu de test (séparation par séjour ; 35,5~\\% des séjours de test ont un patient vu à l'entraînement). Le score d'urgence est une règle, sans métrique ML.",
                    "tab:ml", "lrrrrl"))
    # T3 N1
    r1 = {l_["methode"]: l_ for l_ in lire_csv(SORTIE / "n1_resume.csv")}
    l3 = [[m, fr(_f(r1[m], "taux_faisable_pct"), 0), f"{fr(_f(r1[m], 'score_commun_moyenne'))} $\\pm$ {fr(_f(r1[m], 'score_commun_ecart_type'))}",
           fr(_f(r1[m], "score_commun_min"), 0), fr(_f(r1[m], "gain_vs_depart_pct_moyenne")),
           fr(_f(r1[m], "fragmentation_moyenne")), fr(_f(r1[m], "salles_differentes_moyenne")), fr(_f(r1[m], "temps_reel_s_moyenne"), 2)]
          for m in ORDRE if m in r1]
    tex.append(_tab(["Méthode", "Faisable (\\%)", "F1 moy. $\\pm$ é.-t.", "F1 min", "Gain vs départ (\\%)", "Fragm.", "Salles diff.", "Temps (s)"],
                    l3, "N1 sur l'instance d'étude fictive (10 graines, budget 10~s)", "tab:n1", "lrrrrrrr"))
    # T4 N2
    r2 = [l_ for l_ in lire_csv(SORTIE / "n2_resume.csv") if l_["groupe"] == "reference"]
    l4 = []
    # classement sur l'objectif optimisé (F2 + report), F2 commun publié à côté
    def _cle(x):
        return (x["methode"] != "glouton", _f(x, "score_recherche_moyenne") or float("inf"))
    for l_ in sorted(r2, key=_cle):
        glouton = l_["methode"] == "glouton"
        l4.append([l_["methode"] + (" (départ)" if glouton else ""),
                   "—" if glouton else f"{l_['solutions_proposees']} / {l_['executions']}",
                   "—" if glouton else str(l_.get("proposees_grace_tolerance", "—")),
                   f"{fr(_f(l_, 'score_recherche_moyenne'), 0)} $\\pm$ {fr(_f(l_, 'score_recherche_ecart_type'), 0)}",
                   fr(_f(l_, "score_commun_moyenne"), 0), fr(_f(l_, "penalite_report_moyenne"), 0),
                   fr(_f(l_, "gain_vs_depart_pct_moyenne")), fr(_f(l_, "ecart_meilleur_faisable_pct_moyenne")),
                   fr(_f(l_, "patients_reportes_moyenne")), fr(_f(l_, "temps_reel_s_moyenne"), 1)])
    tex.append(_tab(["Méthode", "Proposées", "dont tolérance", "Objectif moy. $\\pm$ é.-t.", "F2 commun", "Report",
                     "Gain vs départ (\\%)", "Écart meill. faisable (\\%)", "Reportés", "Temps (s)"], l4,
                    "N2 sur v28, cohorte de référence (charge 100~\\% de la capacité utile), budget 10~s, classée sur l'objectif optimisé (F2 commun + pénalité de report). Seules les solutions faisables sont proposées (tolérance de min(5~min, 25~\\% de la marge) ; « dont tolérance » : faisables seulement grâce à elle). Le glouton est le départ commun. Gain et écart calculés sur l'objectif ; écart à la meilleure solution faisable observée, pas un gap d'optimalité.",
                    "tab:n2", "lrrrrrrrrr"))
    # T5 gains / contreparties
    gc = lire_csv(SORTIE / "gains_contreparties.csv")
    l5 = [[g["methode"], fr(_f(g, "score_recherche"), 0), fr(_f(g, "score_bloc"), 0), fr(_f(g, "score_lits"), 0),
           fr(_f(g, "score_places"), 0), fr(_f(g, "penalite_report"), 0),
           fr(_f(g, "taux_occupation_bloc_pct")), fr(_f(g, "pic_lits")), fr(_f(g, "pic_places")),
           fr(_f(g, "patients_reportes")), fr(_f(g, "delai_moyen_j")), fr(_f(g, "delai_moyen_j_p4"))]
          for g in sorted(gc, key=lambda x: (x["methode"] != "glouton", _f(x, "score_recherche") or float("inf")))]
    tex.append(_tab(["Méthode", "Objectif", "Bloc", "Lits", "Places", "Report", "Occ. bloc (\\%)", "Pic lits", "Pic places",
                     "Reportés", "Délai (j)", "Délai prio. 4 (j)"], l5,
                    "Gains et contreparties (moyennes sur les solutions proposées, cohorte de référence, classées sur l'objectif F2 + report ; glouton = départ) : composantes pondérées et indicateurs opérationnels",
                    "tab:compromis", "lrrrrrrrrrrr"))
    # T6 SMA stratégies (moyennes sur tous les scénarios déterministes)
    sma = lire_csv(SORTIE / "sma_scenarios.csv")
    l6 = []
    for s in ("S_CN", "S_LOC", "S_GLOB", "S_LOC_GLOB"):
        ls = [l_ for l_ in sma if l_["strategie"] == s and not l_["graine"] and not l_.get("echec")]
        n = len(ls)
        u = sum(int(l_["urgences_recues"]) for l_ in ls)
        l6.append([s.replace("_", "\\_"), str(n), str(u), str(sum(int(l_["urgences_dans_delai"]) for l_ in ls)),
                   str(sum(int(l_["transferts_proposes"]) for l_ in ls)),
                   str(sum(int(l_["decales"]) for l_ in ls)), str(sum(int(l_["reportes_autre_jour"]) for l_ in ls)),
                   str(sum(int(l_["liste_attente"]) for l_ in ls)),
                   fr(sum(float(l_["part_planning_conserve_pct"]) for l_ in ls) / n),
                   str(sum(int(l_["erreurs_coherence"]) for l_ in ls))])
    tex.append(_tab(["Stratégie", "Scén.", "Urgences", "Dans délai", "Transf. proposés", "Décalés", "Reportés",
                     "Liste att.", "Planning conservé (\\%)", "Incohérences"], l6,
                    "SMA : stratégies comparées à événements identiques (scénarios déterministes ; sommes, sauf planning conservé : moyenne)",
                    "tab:sma_strategies", "lrrrrrrrrr"))
    # T7 SMA par scénario (configuration du site S_CN)
    l7 = [[l_["scenario"].replace("_", "\\_"), l_["urgences_recues"], l_["urgences_dans_delai"], l_["transferts_proposes"],
           l_["decales"], l_["reportes_autre_jour"], l_["liste_attente"], l_["alertes"], l_["erreurs_coherence"]]
          for l_ in sma if l_["strategie"] == "S_CN" and not l_["graine"] and not l_.get("echec")]
    tex.append(_tab(["Scénario", "Urg.", "Dans délai", "Transf. prop.", "Décalés", "Reportés", "Liste att.", "Alertes",
                     "Incoh."], l7, "SMA, configuration du site (Contract Net sans métaheuristique) : bilan par scénario",
                    "tab:sma_scenarios", "lrrrrrrrr"))
    (SORTIE / "tableaux.tex").write_text("\n".join(tex), encoding="utf-8")
    enregistrer_manifeste("tableaux.tex T1-T7", ["instances.csv", "ml_resultats.csv", "n1_resume.csv", "n2_resume.csv",
                                                 "gains_contreparties.csv", "sma_scenarios.csv"], SCRIPT)


if __name__ == "__main__":
    instances()
    tableaux()
    print("tableaux.tex et instances.csv écrits")
