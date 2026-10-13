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
    C.entete("Historique")

    ok, _, rompu = DB.verifier_historique()
    if not ok:                          # seule l'altération est signalée
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
    c1, c2 = st.columns([1, 2])
    fin = df["quand"].max().date()
    periode = c1.date_input("Période", value=(max(df["quand"].min().date(), fin - timedelta(days=30)), fin),
                            format="DD/MM/YYYY")
    toutes = sorted(df["categorie"].dropna().unique())
    cats = c2.multiselect("Catégories", toutes, default=[c for c in CATEGORIES_PATIENT if c in toutes] or toutes,
                          placeholder="Toutes")

    vue = df
    if isinstance(periode, tuple) and len(periode) == 2:
        vue = vue[(vue["quand"].dt.date >= periode[0]) & (vue["quand"].dt.date <= periode[1])]
    if cats:
        vue = vue[vue["categorie"].isin(cats)]

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

    complet = vue.drop(columns=["quand"]).sort_values("id")
    if st.download_button("Exporter la sélection (CSV, sceaux complets)", complet.to_csv(index=False, sep=";"),
                          file_name=f"historique_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv"):
        C.tracer("export de l'historique", f"{len(complet)} entrée(s)")
