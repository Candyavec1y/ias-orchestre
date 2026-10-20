# -*- coding: utf-8 -*-
"""
Onglet PLANNING :
  1. Vacations des chirurgiens — planning fixe (planning_vacations_v28, parité des semaines) ;
  2. Programme opératoire — état courant (programme des métaheuristiques + corrections du SMA).
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
    C.entete("Planning")
    if C.est("admin"):                  # l'administrateur voit déjà tout le programme : pas d'onglet « Bloc »
        t1, t2 = st.tabs(["Vacations des chirurgiens", "Programme opératoire"])
        t3 = None
    else:
        t1, t2, t3 = st.tabs(["Vacations des chirurgiens", "Programme opératoire", "Bloc"])
    with t1:
        _vacations()
    with t2:
        _programme()
    if t3 is not None:
        with t3:
            _bloc()


# =============================================================================
# 1. Vacations
# =============================================================================

def grille_html(cases: list[P.CaseVacation], lundi: date, moi: str = "",
                operations: dict[int, str] | None = None) -> str:
    """`operations` : vacation_id -> détail HTML ; ces cases deviennent cliquables et déplient leurs opérations."""
    operations = operations or {}
    absents = C.absences()
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
                if c.type == "vacation" and C.est_absent(c.code, c.jour, absents):
                    cls += " absent"
                    lib += " <span class='loupe'>absent</span>"
                if c.vacation_id in operations:
                    cell += (f"<details class='vac {cls} cliquable'><summary>{lib} <span class='loupe'>détail</span>"
                             f"<small>{c.debut} – {c.fin}</small></summary>{operations[c.vacation_id]}</details>")
                else:
                    cell += f"<div class='vac {cls}'>{lib}<small>{c.debut} – {c.fin}</small></div>"
            h += f"<td>{cell}</td>"
        h += "</tr>"
    return h + "</table>"


def _decaler_semaine(n: int) -> None:
    st.session_state["sem_vac"] = P.lundi_de(st.session_state["sem_vac"]) + timedelta(weeks=n)


def _libelle_semaine(lundi: date) -> str:
    ven = lundi + timedelta(days=4)
    debut = f"{lundi.day}" if lundi.month == ven.month else f"{lundi.day} {C.MOIS[lundi.month - 1]}"
    return f"Semaine du {debut} au {ven.day} {C.MOIS[ven.month - 1]} {ven.year}"


def _vacations() -> None:
    u = C.utilisateur()
    st.session_state.setdefault("sem_vac", C.maintenant().date())
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([0.8, 1.3, 0.8, 2.6], vertical_alignment="bottom")
        c1.button("← Précédente", on_click=_decaler_semaine, args=(-1,), width="stretch")
        jour = c2.container(key="selecteur_semaine").date_input("Semaine", format="DD/MM/YYYY", key="sem_vac")
        c3.button("Suivante →", on_click=_decaler_semaine, args=(1,), width="stretch")
        lundi = P.lundi_de(jour)
        type_sem, cases = P.planning_semaine_v28(lundi)
        c4.markdown(f"<div class='petit'>{_libelle_semaine(lundi)} · {C.libelle_semaine(type_sem)}</div>",
                    unsafe_allow_html=True)
    st.markdown(grille_html(cases, lundi, u.get("praticien", ""), _operations_cliquables(cases)),
                unsafe_allow_html=True)
    st.caption("Cycle de 4 semaines (impaire A, paire, impaire B, paire) déduit de la date. Les vacations qui "
               "enjambent la pause de 13 h–13 h 30 sont coupées en deux. "
               + ("Vos vacations sont mises en évidence : cliquez sur l'une d'elles pour voir vos opérations."
                  if u["role"] == "chirurgien" else "Cliquez sur une vacation pour voir ses opérations."))
    if u["role"] != "chirurgien":
        with st.expander("Heures de vacation par chirurgien cette semaine"):
            h = P.heures_par_praticien(cases)
            st.dataframe(pd.DataFrame({"Chirurgien": [f"Dr {k}" for k in h],
                                       "Heures": [round(x, 1) for x in h.values()]}),
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
                + ("" if cid is not None else f" · {escape(S.nom_chirurgien(it.chirurgien_id))}")
                + f"<br>{'ambulatoire' if it.patient.ambulatoire else f'hospit. {it.patient.nuits_post_op} n.'}"
                f" · prio {it.patient.priorite}{' · fait' if it.fin <= sim.maintenant else ''}</td></tr>"
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
    jour = c1.container(key="selecteur_jour_prog").selectbox("Jour", jours, index=jours.index(defaut),
                                                             format_func=C.jour_long, key="jour_prog")
    noms = C.noms_patients(sim)
    moi = S.id_chirurgien(u["praticien"]) if u.get("praticien") else None
    # un chirurgien ne voit que son propre programme ; la régulation et l'administrateur voient tout le bloc
    # (dont l'occupation des lits et des places)
    restreint = u["role"] == "chirurgien"
    cadre = u["role"] == "regulation"
    occ = sim.occupation(jour)
    c2.markdown("<br>" + ("" if restreint else
                          C.badge(f"Lits {occ['lits']}/{occ['cap_lits']} (+{occ['reserve']} réserve)",
                                  "rouge" if occ["lits"] > occ["cap_lits"] else "")
                          + C.badge(f"Ambulatoire {occ['places']}/{occ['cap_places']}",
                                    "rouge" if occ["places"] > occ["cap_places"] else ""))
                + (C.badge("monte-lit en panne", "ambre") if sim.pannes() else ""), unsafe_allow_html=True)
    if restreint:
        st.markdown(C.badge(f"Programme de Dr {u.get('praticien') or '?'} uniquement", "bleu"), unsafe_allow_html=True)
    st.plotly_chart(G.gantt_jour(sim, jour, noms, moi, seulement=(moi if moi is not None else -1) if restreint else None),
                    width="stretch", config={"displayModeBar": False})
    st.caption(("Vos vacations et vos interventions uniquement (les opérations des autres chirurgiens ne sont pas "
                "affichées). " if restreint else "")
               + "Cadres : vacations (couleur du chirurgien) et plages d'urgences (rouge). Barres : interventions ; "
               "hachures = ambulatoire ; rouge plein = urgence. Survolez une barre pour le détail.")

    lignes = []
    for s in sim.salles(jour):
        for it in s.du_jour(jour):
            if restreint and it.chirurgien_id != moi:
                continue
            d = int((it.debut - it.debut_initial).total_seconds() // 60)
            etat = "Urgence" if it.urgence else ("Reporté" if it.debut_initial.date() != it.debut.date()
                                                  else f"Décalé {d:+d} min" if d else "Conforme")
            if it.chirurgien_id != it.chirurgien_initial:
                etat += " · repris par un confrère"
            lignes.append({"Début": it.debut.strftime("%H:%M"), "Fin": it.fin.strftime("%H:%M"), "Salle": s.nom_affiche,
                           "Chirurgien": f"{S.nom_chirurgien(it.chirurgien_id)}", "Patient": noms.get(it.pid, it.pid),
                           "Durée (min)": it.patient.duree_bloc,
                           "Prise en charge": "Ambulatoire" if it.patient.ambulatoire else f"Hospit. ({it.patient.nuits_post_op} n.)",
                           "Priorité": it.patient.priorite, "État": etat,
                           "Fait": "oui" if it.fin <= sim.maintenant else ""})
    if lignes:
        df = pd.DataFrame(lignes).sort_values(["Salle", "Début"])
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.info("Aucune de vos interventions ce jour." if restreint
                else "Aucune intervention ce jour (week-end ou jour sans vacation).")

    if not restreint and not cadre:
        with st.expander("Occupation des lits et des places ambulatoires sur l'horizon"):
            st.plotly_chart(G.occupation_hebergement(sim), width="stretch", config={"displayModeBar": False})
    attente = [(i, j) for i, j in sim.en_attente() if not restreint or i.chirurgien_initial == moi]
    if attente:
        with st.expander(f"Liste d'attente ({len(attente)})"):
            st.dataframe(pd.DataFrame([{"Patient": noms.get(i.pid, i.pid), "Chirurgien": f"{S.nom_chirurgien(i.chirurgien_initial)}",
                                        "Durée (min)": i.patient.duree_bloc, "Priorité": i.patient.priorite,
                                        "Depuis le": j.strftime("%d/%m")} for i, j in attente]),
                         hide_index=True, width="stretch")


# =============================================================================
# 3. Bloc : occupation des salles, sans aucune information patient
# =============================================================================

def _bloc() -> None:
    sim = C.simulation()
    if sim is None:
        st.info("Aucun programme calculé.")
        return
    jours = sim.jours()
    aujourd = C.maintenant().date()
    if st.session_state.get("jour_bloc") not in jours:
        st.session_state["jour_bloc"] = aujourd if aujourd in jours else next((j for j in jours if j >= aujourd),
                                                                               jours[0])
    st.columns([1, 2])[0].container(key="selecteur_jour_bloc").selectbox("Jour", jours, format_func=C.jour_long,
                                                                         key="jour_bloc")
    st.plotly_chart(G.bloc_occupe(sim, st.session_state["jour_bloc"]), width="stretch",
                    config={"displayModeBar": False})
    st.caption("Cases grisées : salle occupée. Cadres : vacations et plages d'urgences ouvertes ce jour-là.")
