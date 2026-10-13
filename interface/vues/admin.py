# -*- coding: utf-8 -*-
"""Onglet ADMINISTRATION : comptes, horloge de démonstration, conservation (RGPD), traces, modèle."""
from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from orchestre import ml
from orchestre import programme as P
from orchestre import stockage as DB
from vues import commun as C


def afficher() -> None:
    if not C.est("admin"):
        st.error("Accès réservé à l'administrateur.")
        return
    C.entete("Administration")
    t1, t2, t3, t4, t5 = st.tabs(["Comptes", "Horloge", "Conservation des données", "Journal des accès", "Modèle ML"])
    with t1:
        _comptes()
    with t2:
        _horloge()
    with t3:
        _conservation()
    with t4:
        _journal()
    with t5:
        _modele()


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
        if st.button("Confirmer", type="primary"):
            DB.vider_evenements()
            C.tracer("réinitialisation des événements")
            st.rerun()


def _conservation() -> None:
    duree = DB.lire_parametre("duree_conservation_jours", DB.DUREE_CONSERVATION_JOURS_DEFAUT)
    st.markdown("Les données de cette application sont des données **de travail** pour la programmation : le dossier "
                "médical de référence reste le DPI de l'établissement. Elles sont supprimées automatiquement après "
                "l'intervention ; les traces d'accès sont conservées 6 mois.")
    n = st.number_input("Durée de conservation après l'intervention (jours)", 1, 365, int(duree))
    c1, c2 = st.columns(2)
    if c1.button("Enregistrer"):
        DB.ecrire_parametre("duree_conservation_jours", int(n))
        C.tracer("durée de conservation", str(n))
        st.success("Enregistré.")
    if c2.button("Purger maintenant", type="primary"):
        sup = DB.purger(int(n))
        C.tracer("purge RGPD", f"{len(sup)} patient(s)")
        st.success(f"{len(sup)} fiche(s) supprimée(s)." + (" " + ", ".join(sup) if sup else ""))


def _journal() -> None:
    j = DB.lire_journal(1000)
    st.caption("Qui a fait quoi et quand (créations, consultations de fiches, déchiffrements, exports, suppressions, "
               "connexions). Conservation : 6 mois.")
    st.dataframe(pd.DataFrame(j), hide_index=True, width="stretch", height=480)


def _modele() -> None:
    met = ml.metriques()
    if not met:
        st.warning("Jeu de données historique absent : métriques indisponibles.")
        return
    st.markdown(f"Validation **80 % / 20 %** (stratifiée sur la capacité, graine 42) : {met['n_train']} séjours "
                f"d'entraînement, {met['n_test']} de test. Les modèles utilisés en consultation sont ceux du dépôt "
                f"(`outputs/models_rapide`, réentraînés sur 100 % des données).")
    st.dataframe(pd.DataFrame([
        {"Cible": "Ambulatoire / hospitalisation", "Métrique": "exactitude", "Valeur": f"{met['capacite']['accuracy']:.1%}"},
        {"Cible": "Ambulatoire / hospitalisation", "Métrique": "F1 (hospitalisation)", "Valeur": f"{met['capacite']['f1_lit']:.3f}"},
        {"Cible": "Durée au bloc", "Métrique": "erreur moyenne", "Valeur": f"{met['duree_bloc_heures']['mae'] * 60:.0f} min"},
        {"Cible": "Durée au bloc", "Métrique": "R²", "Valeur": f"{met['duree_bloc_heures']['r2']:.3f}"},
        {"Cible": "Nuits après l'opération", "Métrique": "erreur moyenne", "Valeur": f"{met['nuits_apres']['mae']:.2f} nuit"},
        {"Cible": "Nuits après l'opération", "Métrique": "erreur ≤ 1 nuit", "Valeur": f"{met['apres_erreur_le_1j_pct']:.1f} %"},
        {"Cible": "Score d'urgence (1-10)", "Métrique": "exact", "Valeur": f"{met['urgence']['exact_pct']:.1f} %"},
    ]), hide_index=True, width="stretch")
    st.caption("Le score d'urgence de l'historique est lui-même calculé par une règle sur les codes CIM/CCAM "
               "(utilisation_modèle.py) : le modèle apprend cette règle, pas un jugement clinique.")
    if st.button("Recalculer les métriques"):
        with st.spinner("Validation 80/20…"):
            ml.metriques(recalculer=True)
        C.tracer("recalcul des métriques ML")
        st.rerun()
