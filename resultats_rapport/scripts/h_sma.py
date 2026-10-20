# -*- coding: utf-8 -*-
"""
Tâche H : SMA — scénarios (existants + combinaisons définies ici, avec les événements du moteur) et comparaison
de stratégies de régulation À ÉVÉNEMENTS IDENTIQUES (mêmes patients, même programme initial glouton, même graine).

Stratégies disponibles par configuration de ParametresSMA (aucun code modifié) :
    S_CN      Contract Net sans métaheuristique (configuration du SITE) : methode_locale=None, optimisation_globale=None
    S_LOC     + optimisation locale « TABOU seul » (0,02 s par créneau)
    S_GLOB    + optimisation globale « memetique » (1 s par réoptimisation)
    S_LOC_GLOB  locale + globale (valeurs par défaut du moteur)
« Programme figé » et « régulation simple » : NON DISPONIBLES (le moteur n'a pas de mode sans reprogrammation ; les
écrire serait une fonctionnalité métier nouvelle).

Temps réel par événement : mesuré en enveloppant BlocOperatoire._declencher dans ce script (perf_counter).
"""
from __future__ import annotations

import contextlib
import io
import statistics
import sys
import time
from dataclasses import replace
from datetime import date

from commun_rapport import FIGURES, SORTIE, ecrire_csv, enregistrer_manifeste

import scenarios_sma as SC_SMA
import sma_urgences as SMA
from sma_urgences import (ID_PAR_NOM, AbsenceChirurgien, FinPanne, IndisponibiliteLits, PanneAscenseur,
                          ProlongationIntervention, ParametresSMA)

SCRIPT = "scripts/h_sma.py"
STRATEGIES = {"S_CN": dict(methode_locale=None, optimisation_globale=None),
              "S_LOC": dict(methode_locale="TABOU seul", optimisation_globale=None),
              "S_GLOB": dict(methode_locale=None, optimisation_globale="memetique"),
              "S_LOC_GLOB": dict(methode_locale="TABOU seul", optimisation_globale="memetique")}
h, urgence, ORTHO, MAIN, VASC = SC_SMA.h, SC_SMA.urgence, SC_SMA.ORTHO, SC_SMA.MAIN, SC_SMA.VASC

# --- scénarios combinés (événements du moteur ; patients urgents fictifs) ---
COMBINES = {
    "témoin_sans_événement": ("Aucun événement (témoin)", lambda: [], [date(2026, 10, 13)], h(13, 20)),
    "urgence_absence": ("Urgence + absence du chirurgien qui l'a vue",
                        lambda: [AbsenceChirurgien(h(13, 7), ID_PAR_NOM["CT"], date(2026, 10, 13), date(2026, 10, 14), "Maladie"),
                                 urgence(9401, h(13, 9, 30), ORTHO, 60, "urgente")], [date(2026, 10, 13)], h(14, 20)),
    "prolongation_urgence": ("Prolongation de 60 min puis urgence urgente",
                             lambda: [ProlongationIntervention(h(13, 9, 30), 18, 60), urgence(9402, h(13, 10), ORTHO, 60, "urgente")],
                             [date(2026, 10, 13)], h(13, 20)),
    "panne_prolongation": ("Panne du monte-lit + prolongation",
                           lambda: [PanneAscenseur(h(13, 9), "ML1", h(13, 12)), ProlongationIntervention(h(13, 9, 30), 18, 45)],
                           [date(2026, 10, 13)], h(13, 20)),
    "absence_lits": ("Absence + lits fermés",
                     lambda: [AbsenceChirurgien(h(12, 8), ID_PAR_NOM["CT"], date(2026, 10, 13), date(2026, 10, 16), "Congrès"),
                              IndisponibiliteLits(h(12, 8, 30), 10, date(2026, 10, 13), date(2026, 10, 15), "Travaux")],
                     [date(2026, 10, 13)], h(16, 20)),
    "urgence_lits_satures": ("Urgence vitale hospitalisée pendant une fermeture de lits",
                             lambda: [IndisponibiliteLits(h(13, 7), 15, date(2026, 10, 13), date(2026, 10, 15), "Travaux"),
                                      urgence(9403, h(13, 10), ORTHO, 90, "vitale", nuits=3)], [date(2026, 10, 13)], h(14, 20)),
    "urgence_vitale_surcharge": ("Vitale pendant une journée chargée (4 urgences + panne)",
                                 lambda: [urgence(9501, h(15, 8, 10), ORTHO, 90, "urgente", nuits=2),
                                          urgence(9502, h(15, 8, 40), MAIN, 60, "urgente", ambulatoire=True),
                                          PanneAscenseur(h(15, 9), "ML1", h(15, 11)),
                                          urgence(9503, h(15, 9, 30), ORTHO, 120, "vitale", nuits=3),
                                          urgence(9504, h(15, 10), ORTHO, 60, "urgente")],
                                 [date(2026, 10, 15)], h(16, 20)),
    "journee_multi_aleas": ("Une journée : urgences, panne, prolongation, lits fermés",
                            lambda: [IndisponibiliteLits(h(14, 7), 5, date(2026, 10, 14), date(2026, 10, 14), "Infection"),
                                     urgence(9601, h(14, 8, 30), ORTHO, 60, "urgente"),
                                     PanneAscenseur(h(14, 9), "ML1", h(14, 10, 30)), FinPanne(h(14, 10), "ML1"),
                                     ProlongationIntervention(h(14, 11), 31, 30),
                                     urgence(9602, h(14, 13), VASC, 90, "vitale", nuits=2),
                                     urgence(9603, h(14, 15), MAIN, 45, "differable", ambulatoire=True)],
                            [date(2026, 10, 14)], h(15, 20)),
}
for nom, (titre, evts, jours, fin) in COMBINES.items():
    SC_SMA.SCENARIOS[nom] = SC_SMA.Scenario(titre, titre, evts, jours, fin, "")
ALEATOIRES = ("semaine_normale", "semaine_surcharge")
GRAINES_ALEA = (1, 2, 3, 4, 5)


def _quantile(v, q):
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def jouer(nom: str, strategie: str, graine: int = 1, gantt: str | None = None, panne=None) -> dict:
    SC_SMA.GRAINE[0] = graine
    sc = SC_SMA.SCENARIOS[nom]
    i1, i2, sol = SC_SMA.instances_par_defaut()
    p = replace(ParametresSMA(), **STRATEGIES[strategie])
    with contextlib.redirect_stdout(io.StringIO()):
        t_c = time.perf_counter()
        m = SMA.BlocOperatoire.depuis_v28(SC_SMA.LUNDI, instances=(i1, i2), solution=sol, verbeux=0, parametres=p)
        t_construction = time.perf_counter() - t_c
        avant = {it.pid: (it.salle_id, it.debut, it.chirurgien_id) for it in m.interventions()}
        occ_avant = m.hebergement.occupation_par_jour()
        if gantt:
            for j in sc.jours:
                m.tracer_gantt(j, FIGURES / f"{gantt}_{j:%d%m}_avant.png", f"{sc.titre} — {SMA.jour_txt(j)} — avant")
        durees: list[tuple[str, float]] = []
        origine = m._declencher

        def chrono(evt):
            t0 = time.perf_counter()
            r = origine(evt)
            durees.append((type(evt).__name__, time.perf_counter() - t0))
            return r
        m._declencher = chrono
        evts = sc.evenements()
        for e in evts:
            m.planifier(e)
        t_s = time.perf_counter()
        m.executer_jusqu_a(sc.fin)
        t_simulation = time.perf_counter() - t_s
        if gantt:
            for j in sc.jours:
                m.tracer_gantt(j, FIGURES / f"{gantt}_{j:%d%m}_apres.png", f"{sc.titre} — {SMA.jour_txt(j)} — après"
                               + (" (panne grisée)" if panne else ""), panne=panne)
    b = m.bilan()
    urg = [d for d in m.regulation.decisions if d["type"] == "urgence"]
    att = [d["attente_min"] for d in urg]
    apres = {it.pid: (it.salle_id, it.debut, it.chirurgien_id) for it in m.interventions()}
    communs = [pid for pid in avant if pid in apres]
    identiques = sum(avant[pid] == apres[pid] for pid in communs)
    occ_apres = m.hebergement.occupation_par_jour()
    jours = sc.jours
    ligne = {"scenario": nom, "titre": sc.titre, "strategie": strategie, "graine": graine if nom in ALEATOIRES else "",
             "evenements": b["evenements"], "urgences_recues": b["urgences_recues"],
             "urgences_programmees": b["urgences_programmees"], "urgences_dans_delai": b["urgences_dans_delai"],
             "urgences_hors_delai": b["urgences_hors_delai"], "urgences_garde": b["urgences_au_planning_de_garde"],
             "transferts_proposes": b["urgences_transferees"], "urgences_sans_solution": b["urgences_non_programmees"],
             "attente_moyenne_min": statistics.fmean(att) if att else None, "attente_mediane_min": statistics.median(att) if att else None,
             "attente_p90_min": _quantile(att, 0.9), "attente_max_min": max(att) if att else None,
             "niveaux_escalade": b["urgences_par_niveau"],
             "patients_initiaux": len(avant), "inchanges_identiques": identiques,
             "part_planning_conserve_pct": 100 * identiques / len(avant) if avant else None,
             "decales": b["patients_decales"], "avances": b["patients_avances"],
             "minutes_decalage": b["minutes_de_decalage_cumulees"], "reportes_autre_jour": b["patients_reportes_autre_jour"],
             "repris_confrere": b["patients_repris_par_un_confrere"], "liste_attente": b["patients_en_liste_attente"],
             "deprogrammes_sans_place": len(avant) - len(communs),
             "alertes": len(b["alertes"]), "messages": b["messages_echanges"],
             "messages_par_performatif": b["messages_par_performatif"],
             "optimisations_locales": b["optimisations_locales"], "reoptimisations_globales": b["reoptimisations_globales"],
             "reoptimisations_appliquees": b["reoptimisations_appliquees"], "score_programme": b["score_programme"],
             "reoptimisations_rejetees_non_faisables": sum(t.motif_rejet.startswith("plan hors")
                                                           for t in m.optimisation.historique),
             "gain_optimisation_globale": b["gain_optimisation_globale"],
             "erreurs_coherence": b["erreurs_de_coherence"],
             "lits_pic_jours_scenario_avant": max((occ_avant[0].get(j, 0) for j in jours), default=0),
             "lits_pic_jours_scenario_apres": max((occ_apres[0].get(j, 0) for j in jours), default=0),
             "places_pic_jours_scenario_avant": max((occ_avant[1].get(j, 0) for j in jours), default=0),
             "places_pic_jours_scenario_apres": max((occ_apres[1].get(j, 0) for j in jours), default=0),
             "temps_construction_s": t_construction, "temps_simulation_reel_s": t_simulation,
             "temps_evenement_median_s": statistics.median([d for _, d in durees]) if durees else None,
             "temps_evenement_p95_s": _quantile([d for _, d in durees], 0.95),
             "temps_evenement_max_s": max((d for _, d in durees), default=None)}
    return ligne, durees


def gantts():
    """Paires de Gantt avant / après (configuration du site, patients synthétiques), panne grisée."""
    for nom, prefixe, panne in (("fracture_panne", "sma_gantt_urgence_panne", (h(13, 10, 15), h(13, 13))),
                                ("urgence_vitale_surcharge", "sma_gantt_surcharge", (h(15, 9), h(15, 11))),
                                ("prolongation_intervention", "sma_gantt_prolongation", None),
                                ("lits_indisponibles", "sma_gantt_lits", None)):
        jouer(nom, "S_CN", gantt=prefixe, panne=panne)


def main():
    lignes, temps_evts = [], []
    noms = [n for n in SC_SMA.SCENARIOS if n not in ALEATOIRES]
    t0 = time.perf_counter()
    for nom in noms:
        for s in STRATEGIES:
            try:
                l_, d = jouer(nom, s)
            except Exception as e:
                lignes.append({"scenario": nom, "strategie": s, "echec": f"ÉCHEC {type(e).__name__}: {e}"})
                continue
            lignes.append(l_)
            temps_evts += [{"scenario": nom, "strategie": s, "type": t, "temps_s": x} for t, x in d]
        print(f"  {nom} ({time.perf_counter() - t0:.0f} s)", flush=True)
    for nom in ALEATOIRES:
        for g in GRAINES_ALEA:
            for s in STRATEGIES:
                try:
                    l_, d = jouer(nom, s, g)
                except Exception as e:                       # défaut du moteur : consigné, jamais masqué
                    lignes.append({"scenario": nom, "strategie": s, "graine": g,
                                   "echec": f"ÉCHEC {type(e).__name__}: {e}"})
                    continue
                lignes.append(l_)
                temps_evts += [{"scenario": nom, "strategie": s, "graine": g, "type": t, "temps_s": x} for t, x in d]
        print(f"  {nom} ({time.perf_counter() - t0:.0f} s)", flush=True)
    ecrire_csv(SORTIE / "sma_scenarios.csv", [{k: (str(v) if isinstance(v, dict) else v) for k, v in l_.items()}
                                             for l_ in lignes])
    enregistrer_manifeste("sma_scenarios.csv", ["sma_scenarios.csv"], SCRIPT)
    print(f"SMA : {len(lignes)} exécutions en {time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gantt":          # Gantt avant / après (non conservés dans figures/)
        gantts()
    elif len(sys.argv) > 1 and sys.argv[1] == "pilote":
        l_, d = jouer("fracture_panne", "S_LOC_GLOB")
        print(l_)
    else:
        main()
