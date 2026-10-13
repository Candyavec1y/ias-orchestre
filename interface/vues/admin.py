# -*- coding: utf-8 -*-
"""Onglet ADMINISTRATION : comptes et horloge de démonstration."""
from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from orchestre import programme as P
from orchestre import stockage as DB
from vues import commun as C


def afficher() -> None:
    if not C.est("admin"):
        st.error("Accès réservé à l'administrateur.")
        return
    C.entete("Administration")
    t1, t2 = st.tabs(["Comptes", "Horloge"])
    with t1:
        _comptes()
    with t2:
        _horloge()


def _comptes() -> None:
    st.dataframe(pd.DataFrame(DB.lister_utilisateurs()), hide_index=True, width="stretch")
    with st.form("nouveau_compte"):
        st.markdown("**Créer un compte nominatif**")
        c1, c2, c3, c4 = st.columns(4)
        login = c1.text_input("Identifiant")
        nom = c2.text_input("Nom affiché", placeholder="Dr XX")
        role = c3.selectbox("Rôle", list(DB.ROLES), format_func=DB.ROLES.get)
        prat = c4.selectbox("Code praticien (chirurgien)", [""] + P.praticiens_v28())
        ok = st.form_submit_button("Créer (mot de passe provisoire)")
    if ok and login.strip():
        mdp = "Tmp-" + secrets.token_urlsafe(10)
        DB.creer_utilisateur(login.strip(), mdp, role, nom or login, prat, doit_changer=True)
        C.tracer("création de compte", login)
        st.success(f"Compte créé. Mot de passe provisoire à transmettre par un canal sûr : `{mdp}`")
    c1, c2 = st.columns(2)
    cible = c1.selectbox("Compte", [u["login"] for u in DB.lister_utilisateurs()])
    if c2.button("Désactiver / réactiver"):
        u = next(x for x in DB.lister_utilisateurs() if x["login"] == cible)
        DB.activer_utilisateur(cible, not u["actif"])
        C.tracer("activation/désactivation de compte", cible)
        st.rerun()


def _horloge() -> None:
    h = C.horloge()
    st.markdown("En production, l'application suit l'heure réelle. Pour une **démonstration**, figez une heure "
                "simulée et avancez-la pour voir le SMA dérouler la journée (interventions terminées, relance de la "
                "liste d'attente à 7 h, fin de panne estimée…).")
    st.markdown(C.badge("heure réelle" if h.get("mode") != "demo" else f"démonstration : {h['instant']}",
                        "vert" if h.get("mode") != "demo" else "ambre"), unsafe_allow_html=True)
    now = C.maintenant()
    c1, c2, c3 = st.columns(3)
    d = c1.date_input("Date", value=now.date(), format="DD/MM/YYYY")
    t = c2.time_input("Heure", value=now.time(), step=300)
    if c3.button("Fixer l'heure simulée", type="primary"):
        C.regler_horloge(datetime.combine(d, t))
        C.tracer("horloge de démonstration", f"{d} {t}")
        st.rerun()
    b1, b2, b3, b4 = st.columns(4)
    for col, lib, delta in ((b1, "+30 min", timedelta(minutes=30)), (b2, "+2 h", timedelta(hours=2))):
        if col.button(lib, width="stretch"):
            C.regler_horloge(now + delta)
            st.rerun()
    if b3.button("Lendemain 7 h 30", width="stretch"):
        C.regler_horloge(datetime.combine(now.date() + timedelta(days=1), time(7, 30)))
        st.rerun()
    if b4.button("Revenir à l'heure réelle", width="stretch"):
        C.regler_horloge(None)
        st.rerun()
    st.divider()
    with st.popover("Réinitialiser la démonstration"):
        st.write("Supprime tous les événements (inscriptions, urgences, pannes). Les fiches patients sont conservées "
                 "avec le statut « à programmer ».")
        with st.form("form_reinit", border=False):
            motif = st.text_input("Motif (obligatoire, tracé)")
            ok_r = st.form_submit_button("Confirmer", type="primary")
        if ok_r and not motif.strip():
            st.error("Indiquez le motif de la réinitialisation.")
        elif ok_r:
            C.appliquer(DB.vider_evenements, categorie="Programme", action="Réinitialisation de tous les événements",
                        motif=motif.strip())
            st.rerun()
