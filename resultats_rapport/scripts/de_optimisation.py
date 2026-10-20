# -*- coding: utf-8 -*-
"""
Tâches D (N1, instance d'étude fictive) et E (N2, planning réel v28) : campagnes à budget de temps égal.

Chaque exécution appelle hybridation._executer_niveau (même fonction que la campagne du projet : même départ, même
budget, score final recalculé par la fonction objectif COMMUNE, faisabilité par le validateur indépendant).
« Premier créneau compatible » est un adaptateur isolé (ce fichier), pas une méthode du projet.

Exécutions en parallèle (4 processus sur un M2 4 cœurs performance + 4 efficacité) : l'ordre des tâches est
mélangé pour que l'éventuel passage sur un cœur d'efficacité ne favorise aucune méthode ; le nombre d'évaluations
de chaque exécution est enregistré.

    python de_optimisation.py pilote      # 1 graine, 2 s : vérifie la chaîne (sorties séparées, préfixe pilote_)
    python de_optimisation.py final       # campagne P0 + P1
"""
from __future__ import annotations

import contextlib
import io
import json
import multiprocessing as mp
import random
import sys
import time
from datetime import timedelta
from functools import lru_cache

from commun_rapport import AGREGEES, METHODES, SORTIE, commit_git, ecrire_csv, ecrire_json

LUNDI = None   # rempli dans _init (date de commun/parametres.py)
CHARGES = {70: 0.63, 85: 0.765, 100: 0.90, 115: 1.035}   # % de la capacité utile visé -> charge du générateur
COHORTE_REF = 43                                          # GRAINE_PATIENTS (graine de génération des patients)


def _init():
    global LUNDI
    import commun_rapport  # noqa: F401  (chemins du dépôt)
    from parametres import LUNDI_REFERENCE
    LUNDI = LUNDI_REFERENCE


@lru_cache(maxsize=8)
def instance_n2(charge_pct: int, cohorte: int):
    import hybridation as H
    _init()
    base = H.instance_v28(LUNDI, 4, graine=cohorte, charge=CHARGES[charge_pct])
    return base, H.etendre_horizon(base, H.NB_SEMAINES_REPORT)


@lru_cache(maxsize=1)
def instance_n1():
    import hybridation as H
    return H.charger_instances("etude")[0]


def _premier_creneau(inst2):
    """Adaptateur : chaque patient (date au plus tôt, priorité décroissante) dans la PREMIÈRE vacation de son
    chirurgien, à partir de sa date au plus tôt, qui respecte capacité utile, lits et places ; sinon non placé."""
    import structures_communes as SC
    etat = SC.EtatNiveau2(inst2)
    par_chir = {}
    for v in sorted(inst2.vacations.values(), key=lambda v: (v.jour, v.heure_debut, v.id)):
        par_chir.setdefault(v.chirurgien_id, []).append(v)
    for p in sorted(inst2.patients.values(), key=lambda p: (p.date_min or LUNDI, -p.priorite, p.id)):
        for v in par_chir.get(p.chirurgien_id, []):
            if v.jour >= (p.date_min or LUNDI) and etat.peut_placer(p.id, v.id):
                etat.deplacer(p.id, v.id)
                break
    return SC.SolutionPatients(dict(etat.aff))


def _metriques_n2(r, inst2) -> dict:
    """Indicateurs agrégés d'une solution N2 (aucune donnée individuelle : patients synthétiques DEMO)."""
    ind = r.indicateurs
    V, P = inst2.vacations, inst2.patients
    h = inst2.hebergement
    import validation as VA
    import structures_communes as SC
    d = {"score_commun": r.score_final, "score_depart": r.score_initial,
         "faisable_strict": VA.valider_niveau2(inst2, SC.SolutionPatients(dict(r.solution)), avec_tolerance=False).faisable,
         "score_recherche": r.score_recherche, "penalite_report": r.detail_score.get("report"),
         "score_bloc": r.detail_score.get("score_blocs"), "score_lits": r.detail_score.get("score_lits"),
         "score_places": r.detail_score.get("score_places"), "faisable": r.faisable,
         "nb_violations": len(r.validation.get("violations", [])),
         "violations_par_type": json.dumps(r.validation.get("par_type", {}), ensure_ascii=False),
         "patients": ind.nb_patients, "places": ind.nb_places, "non_places": ind.nb_non_places,
         "taux_occupation_bloc_pct": ind.taux_occupation_bloc_pct, "capacite_bloc_min": ind.capacite_bloc_minutes,
         "charge_bloc_min": ind.charge_bloc_minutes, "temps_inoccupe_min": ind.temps_inoccupe_minutes,
         "depassement_bloc_min": ind.depassement_bloc_minutes, "vacations_vides": ind.nb_vacations_vides,
         "vacations_en_depassement": ind.nb_vacations_en_depassement,
         "vacations_report_utilisees": ind.nb_vacations_supp_utilisees, "patients_reportes": ind.patients_en_supp,
         "pic_lits": ind.pic_lits, "cap_lits": h.cap_lits, "depassement_lits": ind.depassement_lits,
         "taux_occupation_lits_pct": ind.taux_occupation_lits_pct,
         "jours_lits_pleins": sum(o >= h.cap_lits for o in ind.occupation_lits_par_jour.values()),
         "pic_places": ind.pic_places, "cap_places": h.cap_places, "depassement_places": ind.depassement_places,
         "taux_occupation_places_pct": ind.taux_occupation_places_pct,
         "jours_places_pleines": sum(o >= h.cap_places for o in ind.occupation_places_par_jour.values())}
    delais, semaines = {}, {}
    for pid, vid in r.solution.items():
        p = P[pid]
        if vid is None:
            continue
        v = V[vid]
        delais.setdefault(p.priorite, []).append((v.jour - (p.date_min or LUNDI)).days)
        semaines.setdefault(p.priorite, []).append(v.semaine_decalage if v.supplementaire else 0)
    tous = [x for l_ in delais.values() for x in l_]
    d["delai_moyen_j"] = sum(tous) / len(tous) if tous else None
    d["delai_max_j"] = max(tous) if tous else None
    d["semaines_report_total"] = sum(x for l_ in semaines.values() for x in l_)
    for prio in (1, 2, 3, 4):
        l_ = delais.get(prio, [])
        d[f"delai_moyen_j_p{prio}"] = sum(l_) / len(l_) if l_ else None
        d[f"delai_max_j_p{prio}"] = max(l_) if l_ else None
        d[f"reportes_p{prio}"] = sum(x > 0 for x in semaines.get(prio, []))
        d[f"non_places_p{prio}"] = sum(1 for pid, vid in r.solution.items() if vid is None and P[pid].priorite == prio)
    return d


def executer(tache: dict) -> dict:
    """Une exécution (processus de travail). Sortie standard du projet supprimée."""
    import hybridation as H
    import sorties as SO
    _init()
    t0 = time.perf_counter()
    niveau, methode, graine, budget = tache["niveau"], tache["methode"], tache["graine"], tache["budget_s"]
    inst = instance_n1() if niveau == 1 else instance_n2(tache["charge_pct"], tache["cohorte"])[1]
    t_inst = time.perf_counter() - t0
    with contextlib.redirect_stdout(io.StringIO()):
        if methode in ("glouton", "premier créneau"):
            pbc = H.ProblemeHybrideN1 if niveau == 1 else H.ProblemeHybrideN2
            pb = pbc(inst, H.Journal(SO.SuiviExecution()))
            suivi = SO.SuiviExecution()
            with suivi:
                depart = pb.solution_initiale(random.Random(graine))
                sol = depart if methode == "glouton" else _premier_creneau(inst)
            s0 = pb.evaluer(depart)
            fab = SO.resultat_niveau1 if niveau == 1 else SO.resultat_niveau2
            r = fab(methode, inst, sol, score_initial=s0, suivi=suivi, graine=graine, variante=methode)
            if niveau == 2:
                r.score_recherche = pb.cout(pb.depuis_solution(sol))
                r.detail_score["report"] = pb.etat(pb.depuis_solution(sol)).report
        else:
            r = H._executer_niveau(niveau, inst, [methode], budget, graine, H.ParametresRechercheLocale())[0]
    ligne = {**{k: v for k, v in tache.items()}, "temps_reel_s": r.temps_calcul_s, "temps_instance_s": t_inst,
             "evaluations": r.nb_evaluations, "generations": r.compteurs.get("generations", 0)}
    if niveau == 1:
        i = r.indicateurs
        ligne.update({"score_commun": r.score_final, "score_depart": r.score_initial, "faisable": r.faisable,
                      "nb_violations": len(r.validation.get("violations", [])),
                      "violations_par_type": json.dumps(r.validation.get("par_type", {}), ensure_ascii=False),
                      "conflits_salles": i.conflits_salles, "conflits_chirurgiens": i.conflits_chirurgiens,
                      "salles_differentes": i.salles_differentes, "fragmentation": i.fragmentation,
                      "blocs_total": i.nb_blocs_total, "blocs_places": i.nb_blocs_places,
                      "vacations": i.nb_vacations, "heures_demandees": i.heures_demandees,
                      "heures_planifiees": i.heures_planifiees})
    else:
        ligne.update(_metriques_n2(r, inst))
    ligne["convergence"] = [(round(p.temps_s, 4), p.meilleur_score) for p in r.historique]
    ligne["solution"] = {str(k): v for k, v in r.solution.items()}
    return ligne


def plan(mode: str) -> list[dict]:
    taches = []
    pilote = mode == "pilote"
    graines = [1] if pilote else list(range(1, 11))
    budget = 2.0 if pilote else 10.0
    # --- D : N1, 10 graines x 6 méthodes + glouton ---
    for g in graines:
        taches.append(dict(campagne="N1", niveau=1, methode="glouton", graine=g, budget_s=0.0))
        taches += [dict(campagne="N1", niveau=1, methode=m, graine=g, budget_s=budget) for m in METHODES]
    # --- E : N2 cohorte de référence (100 %), 10 graines ---
    def n2(camp, pct, coh, gr, b):
        out = [dict(campagne=camp, niveau=2, methode=m, graine=gr, budget_s=0.0, charge_pct=pct, cohorte=coh)
               for m in ("glouton", "premier créneau")] if gr == gr_min else []
        return out + [dict(campagne=camp, niveau=2, methode=m, graine=gr, budget_s=b, charge_pct=pct, cohorte=coh)
                      for m in METHODES]
    gr_min = graines[0]
    for g in graines:
        taches += n2("N2_reference", 100, COHORTE_REF, g, budget)
    if not pilote:
        # --- E2 / G1 : charges 70 / 85 / 100 / 115 %, 3 cohortes, 3 graines ---
        for pct in CHARGES:
            for coh in (COHORTE_REF, COHORTE_REF + 1, COHORTE_REF + 2):
                if pct == 100 and coh == COHORTE_REF:
                    continue                                   # déjà dans la référence (10 graines)
                for g in (1, 2, 3):
                    taches += n2("N2_charges", pct, coh, g, budget)
        # --- I / G4 : budgets 2, 5, 20 s sur la référence, 3 graines ---
        for b in (2.0, 5.0, 20.0):
            for g in (1, 2, 3):
                taches += [dict(campagne="N2_budgets", niveau=2, methode=m, graine=g, budget_s=b, charge_pct=100,
                                cohorte=COHORTE_REF) for m in METHODES]
    return taches


def main(mode: str):
    taches = plan(mode)
    random.Random(2026).shuffle(taches)
    prefixe = "pilote_" if mode == "pilote" else ""
    estime = sum(t["budget_s"] for t in taches) / 4
    print(f"{len(taches)} exécutions, budget cumulé {sum(t['budget_s'] for t in taches):.0f} s, "
          f"durée estimée ≈ {estime / 60:.0f} min sur 4 processus", flush=True)
    t0 = time.perf_counter()
    resultats = []
    with mp.get_context("spawn").Pool(4) as pool:
        for k, r in enumerate(pool.imap_unordered(executer, taches), 1):
            resultats.append(r)
            if k % 20 == 0:
                print(f"  {k}/{len(taches)} ({time.perf_counter() - t0:.0f} s)", flush=True)
    conv = [{k: r[k] for k in ("campagne", "niveau", "methode", "graine", "budget_s", "charge_pct", "cohorte",
                               "convergence") if k in r} for r in resultats]
    sols = [{k: r[k] for k in ("campagne", "niveau", "methode", "graine", "budget_s", "charge_pct", "cohorte",
                               "solution") if k in r} for r in resultats]
    lignes = [{k: v for k, v in r.items() if k not in ("convergence", "solution")} for r in resultats]
    for niv, nom in ((1, "n1_resultats.csv"), (2, "n2_resultats.csv")):
        ecrire_csv(SORTIE / f"{prefixe}{nom}", sorted([l_ for l_ in lignes if l_["niveau"] == niv],
                                                     key=lambda l_: (l_["campagne"], str(l_.get("charge_pct")),
                                                                     str(l_.get("cohorte")), l_["methode"],
                                                                     l_["graine"], l_["budget_s"])))
    ecrire_json(AGREGEES / f"{prefixe}convergence.json", conv)
    ecrire_json(AGREGEES / f"{prefixe}solutions_synthetiques.json", sols)
    ecrire_json(AGREGEES / f"{prefixe}campagne_meta.json",
                {"commit": commit_git(), "mode": mode, "executions": len(taches), "processus": 4,
                 "duree_totale_s": time.perf_counter() - t0, "charges": CHARGES, "cohorte_reference": COHORTE_REF})
    print(f"Terminé en {time.perf_counter() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pilote")
