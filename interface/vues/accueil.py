# -*- coding: utf-8 -*-
"""Onglet ACCUEIL : la journée en un coup d'œil (chirurgien : uniquement son programme et ses patients du jour)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from orchestre import sma_service as S
from vues import commun as C
from vues import graphiques as G


def afficher() -> None:
    u = C.utilisateur()
    now = C.maintenant()
    st.markdown(f"## Bonjour {u['nom_affiche']}")
    st.markdown(f"<div class='petit'>{C.jour_long(now.date())} — {now:%H:%M}</div>", unsafe_allow_html=True)
    sim = C.simulation()
    if sim is None:
        st.info("Le programme opératoire n'est pas encore calculé.")
        return
    if u["role"] == "chirurgien":
        _accueil_chirurgien(u, sim, now)
        return
    noms = C.noms_patients(sim)
    du_jour = [it for it in sim.interventions() if it.debut.date() == now.date()]
    a_venir = [it for it in du_jour if it.debut > now]
    en_cours = [it for it in du_jour if it.debut <= now < it.fin]
    occ = sim.occupation(now.date())
    b = sim.modele.bilan()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Interventions aujourd'hui", len(du_jour), f"{len(en_cours)} en cours", delta_color="off", delta_arrow="off")
    c2.metric("Restant à opérer", len(a_venir))
    c3.metric("Urgences du jour", sum(it.urgence for it in du_jour))
    c4.metric("Lits occupés", f"{occ['lits']}/{occ['cap_lits']}")
    c5.metric("Ambulatoire", f"{occ['places']}/{occ['cap_places']}")

    for a in b["alertes"][-3:]:
        st.error(C.lisible(a, noms))
    if sim.pannes():
        st.warning("Monte-lit en panne : voir l'onglet Urgences → Incident logistique.")

    st.write("")
    l1, l2, l3, l4 = st.columns(4)
    with l1.container(border=True):
        st.markdown("**Nouvelle consultation**  \n<span class='petit'>Prédictions du modèle et créneaux proposés</span>",
                    unsafe_allow_html=True)
        st.page_link(_page("consultation"), label="Ouvrir")
    with l2.container(border=True):
        st.markdown("**Planning**  \n<span class='petit'>Vacations et programme opératoire du jour</span>",
                    unsafe_allow_html=True)
        st.page_link(_page("planning"), label="Ouvrir")
    with l3.container(border=True):
        st.markdown("**Urgences**  \n<span class='petit'>Insérer une urgence, déclarer un incident</span>",
                    unsafe_allow_html=True)
        st.page_link(_page("urgences"), label="Ouvrir")
    with l4.container(border=True):
        st.markdown("**Patients**  \n<span class='petit'>Statut, annulation, droits des patients</span>",
                    unsafe_allow_html=True)
        st.page_link(_page("patients"), label="Ouvrir")

    if u.get("praticien"):
        cid = S.id_chirurgien(u["praticien"])
        mes = [it for it in sim.interventions() if it.chirurgien_id == cid and it.fin > now]
        st.markdown("#### Mes prochaines interventions")
        if not mes:
            st.caption("Aucune intervention programmée sur l'horizon.")
        else:
            st.dataframe(pd.DataFrame([{
                "Jour": C.jour_long(it.debut.date()), "Heure": f"{it.debut:%H:%M}–{it.fin:%H:%M}",
                "Salle": sim.modele.salles[it.salle_id].nom_affiche, "Patient": noms.get(it.pid, it.pid),
                "Durée (min)": it.patient.duree_bloc,
                "Prise en charge": "Ambulatoire" if it.patient.ambulatoire else "Hospitalisation",
                "Urgence": "oui" if it.urgence else ""} for it in mes[:15]]), hide_index=True, width="stretch")


def _accueil_chirurgien(u: dict, sim: S.Simulation, now) -> None:
    if not u.get("praticien"):
        st.info("Aucun praticien n'est associé à ce compte : contactez l'administrateur.")
        return
    moi = S.id_chirurgien(u["praticien"])
    noms = C.noms_patients(sim)
    jour = now.date()
    mes = sorted((it for it in sim.interventions() if it.debut.date() == jour and it.chirurgien_id == moi),
                 key=lambda it: it.debut)
    vacations = [f for f in sim.fenetres_du_jour(jour) if f.chirurgien_id == moi]

    urgences = [it for it in mes if it.urgence]
    if urgences:
        st.markdown("#### Urgences du jour")
        for it in urgences:
            etat = "terminée" if it.fin <= now else "en cours" if it.debut <= now else "à venir"
            st.error(f"**{noms.get(it.pid, it.pid)}** · {it.debut:%H:%M}–{it.fin:%H:%M} · "
                     f"{sim.modele.salles[it.salle_id].nom_affiche} · {etat}")

    st.markdown("#### Mon planning du jour")
    if not mes and not vacations:
        st.info("Aucune vacation ni intervention programmée aujourd'hui.")
        return
    st.plotly_chart(G.gantt_jour(sim, jour, noms, moi, seulement=moi), width="stretch",
                    config={"displayModeBar": False})

    st.markdown("#### Mes patients du jour")
    if not mes:
        st.caption("Aucun patient programmé sur vos vacations aujourd'hui.")
        return
    st.dataframe(pd.DataFrame([{
        "Heure": f"{it.debut:%H:%M}–{it.fin:%H:%M}", "Salle": sim.modele.salles[it.salle_id].nom_affiche,
        "Patient": noms.get(it.pid, it.pid), "Durée (min)": it.patient.duree_bloc,
        "Prise en charge": "Ambulatoire" if it.patient.ambulatoire else f"Hospitalisation ({it.patient.nuits_post_op} n.)",
        "Priorité": it.patient.priorite, "Urgence": "oui" if it.urgence else "",
        "Statut": "Terminée" if it.fin <= now else "En cours" if it.debut <= now else "À venir"} for it in mes]),
        hide_index=True, width="stretch")


def _page(nom: str):
    """Retrouve l'objet Page déclaré dans app.py (st.page_link accepte un st.Page)."""
    for p in st.session_state.get("_pages", []):
        if p.url_path == nom:
            return p
    return nom
