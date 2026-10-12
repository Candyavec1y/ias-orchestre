# -*- coding: utf-8 -*-
"""
Onglet PLANNING :
  1. Vacations des chirurgiens — planning fixe (planning_vacations_v28, parité des semaines) ;
  2. Programme opératoire — état courant (programme des métaheuristiques + corrections du SMA) ;
  3. Optimisation — provenance du programme, recalcul et comparaison des métaheuristiques / hybridations,
     recalcul du planning des vacations (niveau 1).
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from orchestre import programme as P
from orchestre import sma_service as S
from vues import commun as C
from vues import graphiques as G


def afficher() -> None:
    C.entete("📅 Planning", "Planning fixe des vacations, programme opératoire du jour et métaheuristiques "
                            "qui le calculent.")
    t1, t2, t3 = st.tabs(["Vacations des chirurgiens", "Programme opératoire", "Optimisation (métaheuristiques)"])
    with t1:
        _vacations()
    with t2:
        _programme()
    with t3:
        _optimisation()


# =============================================================================
# 1. Vacations
# =============================================================================

def grille_html(cases: list[P.CaseVacation], lundi: date, moi: str = "",
                operations: dict[int, str] | None = None) -> str:
    """`operations` : vacation_id -> détail HTML ; ces cases deviennent cliquables et déplient leurs opérations."""
    operations = operations or {}
    jours = [lundi + timedelta(days=k) for k in range(5)]
    salles = sorted({(c.salle_id, c.salle) for c in cases})
    h = "<table class='grille'><tr><th></th>" + "".join(f"<th>{C.jour_long(j)}</th>" for j in jours) + "</tr>"
    for sid, nom in salles:
        h += f"<tr><td class='salle'>{escape(nom)}</td>"
        for j in jours:
            cell = ""
            for c in sorted((c for c in cases if c.salle_id == sid and c.jour == j), key=lambda c: c.debut):
                cls = c.type + (" moi" if c.code == moi else "")
                lib = {"urgence": "Plage URGENCES", "libre": "Plage libre"}.get(
                    c.type, escape(c.code) if c.code.startswith("Dr") else f"Dr {escape(c.code)}")
                if c.vacation_id in operations:
                    cell += (f"<details class='vac {cls} cliquable'><summary>{lib} <span class='loupe'>🔍</span>"
                             f"<small>{c.debut} – {c.fin}</small></summary>{operations[c.vacation_id]}</details>")
                else:
                    cell += f"<div class='vac {cls}'>{lib}<small>{c.debut} – {c.fin}</small></div>"
            h += f"<td>{cell}</td>"
        h += "</tr>"
    return h + "</table>"


def _vacations() -> None:
    u = C.utilisateur()
    c1, c2 = st.columns([1, 2])
    jour = c1.date_input("Semaine du", value=C.maintenant().date(), format="DD/MM/YYYY", key="sem_vac")
    lundi = P.lundi_de(jour)
    type_sem, cases = P.planning_semaine_v28(lundi)
    c2.markdown("<br>" + C.badge(C.libelle_semaine(type_sem), "bleu")
                + C.badge(f"{lundi:%d/%m} → {lundi + timedelta(days=4):%d/%m/%Y}")
                + C.badge("source : planning_vacations_v28"), unsafe_allow_html=True)
    st.markdown(grille_html(cases, lundi, u.get("praticien", ""), _operations_cliquables(cases)),
                unsafe_allow_html=True)
    st.caption("Cycle de 4 semaines (impaire A, paire, impaire B, paire) déduit de la date. Les vacations qui "
               "enjambent la pause de 13 h–13 h 30 sont coupées en deux. "
               + ("Vos vacations sont mises en évidence : cliquez sur l'une d'elles (🔍) pour voir vos opérations."
                  if u["role"] == "chirurgien" else "Cliquez sur une vacation (🔍) pour voir ses opérations."))
    with st.expander("Heures de vacation par chirurgien cette semaine"):
        h = P.heures_par_praticien(cases)
        st.dataframe(pd.DataFrame({"Chirurgien": [f"Dr {k}" for k in h], "Heures": [round(x, 1) for x in h.values()]}),
                     hide_index=True, width="stretch")


def _operations_vacation(sim: S.Simulation, case: P.CaseVacation, cid: int | None) -> list | None:
    """Interventions de la vacation `case` (du seul chirurgien `cid` s'il est donné) ; None hors horizon."""
    if case.jour not in sim.jours():
        return None
    fen = next((f for f in sim.fenetres_du_jour(case.jour)
                if f.salle_id == case.salle_id and f"{f.debut:%H:%M}" == case.debut), None)
    if fen is None:
        return None
    return [it for it in sim.modele.salles[case.salle_id].du_creneau(fen.id) if cid is None or it.chirurgien_id == cid]


def _operations_cliquables(cases: list[P.CaseVacation]) -> dict[int, str]:
    """Détail HTML des opérations par vacation. Un chirurgien n'obtient QUE ses vacations et ses opérations :
    celles des autres ne sont même pas envoyées au navigateur. Régulation et administrateur : toutes les cases."""
    u = C.utilisateur()
    sim = C.simulation()
    noms = C.noms_patients(sim) if sim else {}
    if u["role"] == "chirurgien":
        code = u.get("praticien")
        if not code or code not in S.V28.ID_PAR_NOM:
            return {}
        cid = S.id_chirurgien(code)
        visibles = [c for c in cases if c.type == "vacation" and c.code == code]
    else:
        cid = None
        visibles = [c for c in cases if c.type in ("vacation", "urgence")]
    res = {}
    for c in visibles:
        its = _operations_vacation(sim, c, cid) if sim else None
        if its is None:
            corps = "<div class='ops-vide'>Hors de l'horizon du programme opératoire.</div>"
        elif not its:
            corps = "<div class='ops-vide'>Aucune opération programmée.</div>"
        else:
            lignes = "".join(
                f"<tr><td>{it.debut:%H:%M}–{it.fin:%H:%M}</td><td><b>{escape(str(noms.get(it.pid, it.pid)))}</b>"
                + ("" if cid is not None else f" · Dr {escape(S.code_chirurgien(it.chirurgien_id))}")
                + f"<br>{'ambulatoire' if it.patient.ambulatoire else f'hospit. {it.patient.nuits_post_op} n.'}"
                f" · prio {it.patient.priorite}{' · ✓ fait' if it.fin <= sim.maintenant else ''}</td></tr>"
                for it in its)
            occupe = sum(it.patient.duree_bloc for it in its)
            corps = (f"<table class='ops'>{lignes}</table>"
                     f"<div class='ops-vide'>{len(its)} opération(s) · {occupe} / {c.minutes} min</div>")
        res[c.vacation_id] = corps
    return res


# =============================================================================
# 2. Programme opératoire (état courant du SMA)
# =============================================================================

def _programme() -> None:
    sim = C.simulation()
    if sim is None:
        st.info("Aucun programme calculé.")
        return
    u = C.utilisateur()
    jours = sim.jours()
    aujourd = C.maintenant().date()
    defaut = next((j for j in jours if j >= aujourd), jours[0])
    c1, c2 = st.columns([1, 2])
    jour = c1.selectbox("Jour", jours, index=jours.index(defaut), format_func=C.jour_long, key="jour_prog")
    occ = sim.occupation(jour)
    c2.markdown("<br>" + C.badge(f"Lits {occ['lits']}/{occ['cap_lits']} (+{occ['reserve']} réserve)",
                                 "rouge" if occ["lits"] > occ["cap_lits"] else "")
                + C.badge(f"Ambulatoire {occ['places']}/{occ['cap_places']}",
                          "rouge" if occ["places"] > occ["cap_places"] else "")
                + (C.badge("monte-lit en panne", "ambre") if sim.pannes() else ""), unsafe_allow_html=True)
    noms = C.noms_patients(sim)
    moi = S.id_chirurgien(u["praticien"]) if u.get("praticien") else None
    # un chirurgien ne voit que son propre programme ; la régulation et l'administrateur voient tout le bloc
    restreint = u["role"] == "chirurgien"
    if restreint:
        st.markdown(C.badge(f"Programme de Dr {u.get('praticien') or '?'} uniquement", "bleu"), unsafe_allow_html=True)
    st.plotly_chart(G.gantt_jour(sim, jour, noms, moi, seulement=(moi if moi is not None else -1) if restreint else None),
                    width="stretch", config={"displayModeBar": False})
    st.caption(("Vos vacations et vos interventions uniquement (les opérations des autres chirurgiens ne sont pas "
                "affichées). " if restreint else "")
               + "Cadres : vacations (couleur du chirurgien) et plages d'urgences (rouge). Barres : interventions ; "
               "hachures = ambulatoire ; rouge plein = urgence. Survolez une barre pour le détail.")

    lignes = []
    for s in sim.modele.salles.values():
        for it in s.du_jour(jour):
            if restreint and it.chirurgien_id != moi:
                continue
            d = int((it.debut - it.debut_initial).total_seconds() // 60)
            etat = "Urgence" if it.urgence else ("Reporté" if it.debut_initial.date() != it.debut.date()
                                                  else f"Décalé {d:+d} min" if d else "Conforme")
            if it.chirurgien_id != it.chirurgien_initial:
                etat += " · repris par un confrère"
            lignes.append({"Début": it.debut.strftime("%H:%M"), "Fin": it.fin.strftime("%H:%M"), "Salle": s.nom_affiche,
                           "Chirurgien": f"Dr {S.code_chirurgien(it.chirurgien_id)}", "Patient": noms.get(it.pid, it.pid),
                           "Durée (min)": it.patient.duree_bloc,
                           "Prise en charge": "Ambulatoire" if it.patient.ambulatoire else f"Hospit. ({it.patient.nuits_post_op} n.)",
                           "Priorité": it.patient.priorite, "État": etat,
                           "Fait": "✓" if it.fin <= sim.maintenant else ""})
    if lignes:
        df = pd.DataFrame(lignes).sort_values(["Salle", "Début"])
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.info("Aucune de vos interventions ce jour." if restreint
                else "Aucune intervention ce jour (week-end ou jour sans vacation).")

    with st.expander("Occupation des lits et des places ambulatoires sur l'horizon"):
        st.plotly_chart(G.occupation_hebergement(sim), width="stretch", config={"displayModeBar": False})
    attente = [(i, j) for i, j in sim.en_attente() if not restreint or i.chirurgien_initial == moi]
    if attente:
        with st.expander(f"Liste d'attente ({len(attente)})"):
            st.dataframe(pd.DataFrame([{"Patient": noms.get(i.pid, i.pid), "Chirurgien": f"Dr {S.code_chirurgien(i.chirurgien_initial)}",
                                        "Durée (min)": i.patient.duree_bloc, "Priorité": i.patient.priorite,
                                        "Depuis le": j.strftime("%d/%m")} for i, j in attente]),
                         hide_index=True, width="stretch")
    st.caption("Programme initial fictif (patients DEMO-xxxx générés par le générateur commun de l'étude) "
               "+ patients inscrits en consultation (PAT-…) + urgences (URG-…).")


# =============================================================================
# 3. Optimisation
# =============================================================================

def _optimisation() -> None:
    cfg = C.config_programme()
    peut = C.est("regulation", "admin")
    st.markdown("#### Programme opératoire en vigueur (niveau 2 : patients → vacations)")
    if cfg:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Méthode", P.MODES_HYBRIDES.get(cfg["mode"], cfg["mode"]).split(" (")[0])
        c2.metric("Score glouton (départ)", f"{cfg['score_glouton']:,.0f}".replace(",", " "))
        gain = 100 * (cfg["score_glouton"] - cfg["score_final"]) / cfg["score_glouton"] if cfg["score_glouton"] else 0
        c3.metric("Score final", f"{cfg['score_final']:,.0f}".replace(",", " "), f"-{gain:.1f} %", delta_color="inverse")
        c4.metric("Horizon", f"{cfg['nb_semaines']} semaines", f"à partir du {date.fromisoformat(cfg['lundi']):%d/%m}",
                  delta_color="off", delta_arrow="off")
        st.caption(f"Calculé le {cfg['calcule_le'].replace('T', ' à ')} par {cfg['auteur']}. Fonction objectif commune "
                   "(structures_communes) : 8000 × non placés + 100 × min de dépassement + 1 × min inoccupée + "
                   "5000 × lits/places en trop + 20 × variances d'occupation.")
        if cfg.get("historique"):
            st.plotly_chart(G.convergence({cfg["mode"]: cfg["historique"]}), width="stretch",
                            config={"displayModeBar": False})
        sim = C.simulation()
        prog = C.programme()
        if sim and not (sim.jours()[0] <= C.maintenant().date() <= sim.jours()[-1] + timedelta(days=2)):
            st.warning("La date du jour est hors de l'horizon du programme : recalculez-le pour la semaine en cours.")

    if not peut:
        st.info("Le recalcul du programme et les comparaisons sont réservés à la régulation et à l'administrateur.")
        return

    st.markdown("#### Recalculer le programme")
    with st.form("recalcul"):
        c1, c2, c3 = st.columns(3)
        lundi = c1.date_input("À partir de la semaine du", value=C.maintenant().date(), format="DD/MM/YYYY")
        mode = c2.selectbox("Méthode", list(P.MODES_HYBRIDES), format_func=lambda m: P.MODES_HYBRIDES[m])
        temps = c3.slider("Budget de calcul (s)", 3, 60, 10)
        st.caption("Les inscriptions, urgences et incidents déjà enregistrés sont ensuite REJOUÉS par le SMA sur ce "
                   "nouveau programme (un créneau choisi qui n'existe plus est remplacé par la meilleure alternative).")
        ok = st.form_submit_button("Calculer et remplacer le programme", type="primary")
    if ok:
        with st.spinner(f"{P.MODES_HYBRIDES[mode]} en cours ({temps} s)…"):
            prog = P.calculer_programme(lundi, mode, float(temps))
        C.enregistrer_programme(prog, C.utilisateur()["login"])
        C.tracer("recalcul du programme opératoire", f"{mode}, {temps} s, semaine du {P.lundi_de(lundi)}")
        st.success("Programme remplacé.")
        st.rerun()

    st.markdown("#### Comparer les métaheuristiques (même instance, même départ, même budget)")
    with st.form("comparaison"):
        modes = st.multiselect("Méthodes", [m for m in P.MODES_HYBRIDES if m != "glouton"],
                               default=["memetique", "RS seul", "TABOU seul"], format_func=lambda m: P.MODES_HYBRIDES[m])
        temps_c = st.slider("Budget par méthode (s)", 2, 30, 5)
        ok_c = st.form_submit_button("Lancer la comparaison")
    if ok_c and modes:
        lundi_c = date.fromisoformat(cfg["lundi"]) if cfg else C.maintenant().date()
        with st.spinner(f"{len(modes)} méthode(s) × {temps_c} s…"):
            st.session_state["comparaison_n2"] = P.comparer_algorithmes_n2(lundi_c, modes, float(temps_c))
    if res := st.session_state.get("comparaison_n2"):
        st.dataframe(pd.DataFrame([{"Méthode": P.MODES_HYBRIDES.get(r.variante, r.variante),
                                    "Score départ": round(r.score_initial), "Score final": round(r.score_final),
                                    "Gain %": round(r.gain_pct, 1), "Non placés": r.indicateurs.nb_non_places,
                                    "Occupation bloc %": round(r.indicateurs.taux_occupation_bloc_pct, 1),
                                    "Pic lits": r.indicateurs.pic_lits, "Lits en trop": r.indicateurs.depassement_lits,
                                    "Évaluations": r.nb_evaluations} for r in res]),
                     hide_index=True, width="stretch")
        st.plotly_chart(G.convergence({r.variante: [(p.temps_s, p.meilleur_score) for p in r.historique] for r in res}),
                        width="stretch", config={"displayModeBar": False})

    st.markdown("#### Planning des vacations recalculé (niveau 1 : chirurgiens → plages)")
    st.caption("Le niveau 1 de l'hybridation (hybridage2.py) attribue des blocs de 2 h aux chirurgiens. Il tourne sur "
               "l'instance d'étude commune (8 chirurgiens, 3 salles, semaine du 21/09/2026) : le planning v28 réel "
               "n'est pas découpé en créneaux de 2 h (voir CHOIX.md).")
    with st.form("niveau1"):
        modes1 = st.multiselect("Méthodes", ["memetique", "AGS>RS>TABOU", "RS>AGS>TABOU", "RS seul", "TABOU seul"],
                                default=["memetique", "TABOU seul"])
        t1 = st.slider("Budget par méthode (s)", 2, 30, 5, key="t_n1")
        ok1 = st.form_submit_button("Recalculer le niveau 1")
    if ok1 and modes1:
        with st.spinner("Optimisation du planning des vacations…"):
            st.session_state["resultat_niveau1"] = P.recalculer_planning_niveau1(modes1, float(t1))
    if r1 := st.session_state.get("resultat_niveau1"):
        b = r1.meilleur
        st.markdown(C.badge(f"meilleur : {b.variante}", "vert") + C.badge(f"score {b.score_final:,.0f}".replace(",", " "))
                    + C.badge("faisable" if b.faisable else "NON faisable", "vert" if b.faisable else "rouge")
                    + C.badge("optimum connu de l'étude : 900"), unsafe_allow_html=True)
        lundi1 = min(c.jour for c in r1.cases)
        st.markdown(grille_html(r1.cases, P.lundi_de(lundi1)), unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"Méthode": r.variante, "Score départ": round(r.score_initial),
                                    "Score final": round(r.score_final), "Faisable": r.faisable,
                                    "Conflits": r.indicateurs.conflits_salles + r.indicateurs.conflits_chirurgiens,
                                    "Salles différentes": r.indicateurs.salles_differentes,
                                    "Fragmentation": r.indicateurs.fragmentation, "Vacations": r.indicateurs.nb_vacations}
                                   for r in r1.resultats]), hide_index=True, width="stretch")
