# -*- coding: utf-8 -*-
"""Onglet ACCUEIL : chirurgien = son programme et ses patients du jour ; cadre de bloc = programme de toutes les salles."""
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
    _accueil_cadre(sim, now)


def _accueil_cadre(sim: S.Simulation, now) -> None:
    """Cadre de bloc / régulation : le programme du jour de toutes les salles."""
    st.markdown("#### Programme du bloc aujourd'hui")
    if not sim.fenetres_du_jour(now.date()):
        st.info("Aucune salle ouverte aujourd'hui.")
        return
    st.plotly_chart(G.gantt_jour(sim, now.date(), C.noms_patients(sim)), width="stretch",
                    config={"displayModeBar": False})


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
