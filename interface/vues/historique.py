# -*- coding: utf-8 -*-
"""Onglet HISTORIQUE (administrateur) : traçabilité horodatée, en ajout seul et scellée, de toutes les actions."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from orchestre import stockage as DB
from vues import commun as C

CATEGORIES_PATIENT = ["Programme", "Urgence", "Décision automatique", "Logistique", "Données patient"]


def afficher() -> None:
    if not C.est("admin"):
        st.error("Accès réservé à l'administrateur.")
        return
    C.entete("Historique", "Qui a programmé, déplacé ou annulé quel patient, quand et pourquoi. Journal horodaté, "
                           "en ajout seul et scellé : aucune ligne ne peut être modifiée ni supprimée.")

    ok, n, rompu = DB.verifier_historique()
    if ok:
        st.markdown(C.badge(f"Intégrité vérifiée · {n} entrée(s) · chaîne de scellement intacte", "vert"),
                    unsafe_allow_html=True)
    else:
        st.error(f"ALTÉRATION DÉTECTÉE : la chaîne de scellement est rompue à l'entrée n° {rompu}. "
                 "Le journal a été modifié en dehors de l'application ; conserver la base en l'état et prévenir le "
                 "responsable de la sécurité des systèmes d'information.")

    lignes = DB.lire_historique()
    if not lignes:
        st.info("Aucune action enregistrée pour l'instant.")
        return
    df = pd.DataFrame(lignes)
    df["quand"] = pd.to_datetime(df["horodatage"])

    # ---------------------------------------------------------------- filtres (une seule rangée)
    c1, c2, c3, c4 = st.columns([1.3, 1.6, 1, 1])
    fin = df["quand"].max().date()
    periode = c1.date_input("Période", value=(max(df["quand"].min().date(), fin - timedelta(days=30)), fin),
                            format="DD/MM/YYYY")
    toutes = sorted(df["categorie"].dropna().unique())
    cats = c2.multiselect("Catégories", toutes, default=[c for c in CATEGORIES_PATIENT if c in toutes] or toutes,
                          placeholder="Toutes")
    qui = c3.selectbox("Utilisateur", ["Tous"] + sorted(df["utilisateur"].unique()))
    patient = c4.text_input("Patient", placeholder="ex. URG-001, PAT-26-0003")

    vue = df
    if isinstance(periode, tuple) and len(periode) == 2:
        vue = vue[(vue["quand"].dt.date >= periode[0]) & (vue["quand"].dt.date <= periode[1])]
    if cats:
        vue = vue[vue["categorie"].isin(cats)]
    if qui != "Tous":
        vue = vue[vue["utilisateur"] == qui]
    if patient.strip():
        vue = vue[vue["patient"].fillna("").str.contains(patient.strip(), case=False, regex=False)]

    # ---------------------------------------------------------------- synthèse
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Entrées affichées", len(vue))
    k2.metric("Actions humaines", int((vue["role"] != "automatique").sum()))
    k3.metric("Déplacements automatiques", int((vue["categorie"] == "Décision automatique").sum()))
    k4.metric("Urgences hors délai", int(vue["action"].isin(["Prise en charge HORS DÉLAI",
                                                              "Aucun créneau dans le délai"]).sum()))

    table = pd.DataFrame({
        "Horodatage": vue["quand"].dt.strftime("%d/%m/%Y %H:%M:%S"), "Utilisateur": vue["utilisateur"],
        "Action": vue["action"], "Patient": vue["patient"].fillna(""), "Détail": vue["detail"].fillna(""),
        "Motif": vue["motif"].fillna(""), "Catégorie": vue["categorie"],
        "Rôle": vue["role"].map(lambda r: DB.ROLES.get(r, r)),
        "Heure planning": pd.to_datetime(vue["heure_metier"].replace("", None)).dt.strftime("%d/%m %H:%M").fillna(""),
        "N°": vue["id"], "Sceau": vue["empreinte"].str[:12]})
    st.dataframe(table, hide_index=True, width="stretch", height=min(560, 38 + 35 * max(1, len(table))),
                 column_config={"Horodatage": st.column_config.TextColumn(width="medium"),
                                "Action": st.column_config.TextColumn(width="medium"),
                                "Détail": st.column_config.TextColumn(width="large"),
                                "Motif": st.column_config.TextColumn(width="large"),
                                "N°": st.column_config.NumberColumn(width="small")})
    st.caption("Horodatage : heure légale française du serveur au moment de l'enregistrement. Heure planning : "
               "heure de l'horloge de l'application (différente en mode démonstration). Les déplacements "
               "automatiques sont enregistrés au moment de l'action qui les provoque, avec cette action pour motif.")

    if patient.strip() and not vue.empty:
        with st.expander(f"Parcours chronologique de « {patient.strip()} »", expanded=True):
            for _, l in vue.sort_values("id").iterrows():
                st.markdown(f"**{l['quand']:%d/%m/%Y %H:%M:%S}** · {l['action']} — {l['utilisateur']}  \n"
                            f"<span class='petit'>{l['detail'] or ''}{' · Motif : ' + l['motif'] if l['motif'] else ''}"
                            f"</span>", unsafe_allow_html=True)

    complet = vue.drop(columns=["quand"]).sort_values("id")
    if st.download_button("Exporter la sélection (CSV, sceaux complets)", complet.to_csv(index=False, sep=";"),
                          file_name=f"historique_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv"):
        C.tracer("export de l'historique", f"{len(complet)} entrée(s)")
