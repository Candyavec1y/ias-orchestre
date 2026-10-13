# -*- coding: utf-8 -*-
"""
OR'CHESTRE — aide à la décision pour la programmation du bloc opératoire.

Lancer depuis la racine du dépôt :
    pip install -r interface/requirements.txt
    streamlit run interface/app.py

Onglets : Accueil · Consultation (ML) · Planning (métaheuristiques) · Urgences (SMA) ·
Mes patients · Administration · Confidentialité.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="OR'CHESTRE — Bloc opératoire", page_icon=str(Path(__file__).resolve().parent / "logo.png"), layout="wide",
                   initial_sidebar_state="expanded")

from orchestre import stockage as DB  # noqa: E402
from vues import commun as C  # noqa: E402

DB.initialiser()
C_COMPTES = DB.comptes_de_demonstration()
st.markdown(C.CSS, unsafe_allow_html=True)


# =============================================================================
# Authentification
# =============================================================================

def page_connexion() -> None:
    st.markdown("<div class='arc-deco'></div>", unsafe_allow_html=True)
    _, centre, _ = st.columns([0.22, 1.25, 1.6])
    with centre:
        st.markdown(f"<div class='hero'>{C.marque(nom='IAS')}<div class='titre'>OR'CHESTRE</div>"
                    "<div class='accroche'>Outil d'aide à la décision</div></div>", unsafe_allow_html=True)
        st.markdown("<div class='petit'>Aide à la décision pour la programmation du bloc opératoire — "
                    "accès réservé aux professionnels habilités.</div>", unsafe_allow_html=True)
        if msg := st.session_state.pop("message_connexion", None):
            st.info(msg)
        if C_COMPTES:
            st.warning("Premier lancement : des comptes de démonstration ont été créés. Leurs mots de passe "
                       "provisoires sont dans `interface/donnees/comptes_demo.txt` (à changer à la 1re connexion).")
        with st.form("connexion"):
            login = st.text_input("Identifiant", autocomplete="username")
            mdp = st.text_input("Mot de passe", type="password", autocomplete="current-password")
            ok = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if ok:
            if DB.echecs_recents(login.strip()) >= 5:
                st.error("Compte temporairement bloqué après 5 échecs : réessayez dans 15 minutes.")
                DB.tracer(login.strip() or "?", "-", "tentative sur compte bloqué")
                return
            u = DB.verifier_mot_de_passe(login.strip(), mdp)
            if u is None:
                DB.tracer(login.strip() or "?", "-", "échec de connexion")
                st.error("Identifiant ou mot de passe incorrect.")
                return
            st.session_state["utilisateur"] = {k: u[k] for k in ("login", "nom_affiche", "role", "praticien", "doit_changer")}
            C.tracer("connexion")
            st.rerun()
        st.caption("Les actions réalisées dans l'application sont journalisées (traçabilité des accès aux "
                   "données de santé). Voir l'onglet Confidentialité après connexion.")


def page_changement_mdp() -> None:
    u = C.utilisateur()
    _, centre, _ = st.columns([1, 1.3, 1])
    with centre:
        st.markdown("### Choisissez votre mot de passe personnel")
        st.caption("12 caractères minimum, avec minuscule, majuscule, chiffre et caractère spécial "
                   "(recommandation CNIL).")
        with st.form("mdp"):
            m1 = st.text_input("Nouveau mot de passe", type="password", autocomplete="new-password")
            m2 = st.text_input("Confirmation", type="password", autocomplete="new-password")
            ok = st.form_submit_button("Valider", type="primary", width="stretch")
        if ok:
            pb = DB.mot_de_passe_robuste(m1)
            if m1 != m2:
                st.error("Les deux saisies diffèrent.")
            elif pb:
                st.error("Il manque : " + ", ".join(pb) + ".")
            else:
                DB.changer_mot_de_passe(u["login"], m1)
                u["doit_changer"] = 0
                C.tracer("changement de mot de passe")
                st.success("Mot de passe enregistré.")
                st.rerun()


if not C.utilisateur():
    page_connexion()
    st.stop()
C.verifier_inactivite()
if C.utilisateur().get("doit_changer"):
    page_changement_mdp()
    st.stop()

# =============================================================================
# Navigation
# =============================================================================

from vues import (accueil, admin, confidentialite, consultation, dashboard, historique, patients,  # noqa: E402
                  planning, urgences)

u = C.utilisateur()
if not st.session_state.get("purge_faite"):          # conservation limitée (RGPD) : purge à chaque ouverture de session
    supprimes = DB.purger(DB.lire_parametre("duree_conservation_jours", DB.DUREE_CONSERVATION_JOURS_DEFAUT))
    if supprimes:
        C.tracer("purge automatique RGPD", f"{len(supprimes)} patient(s)")
    st.session_state["purge_faite"] = True
C.garantir_programme()

if u["role"] == "admin":
    st.markdown(C.CSS_ADMIN, unsafe_allow_html=True)

with st.sidebar:
    st.markdown(C.marque("Outil d'aide à la décision"), unsafe_allow_html=True)
    if u["role"] == "admin":
        st.markdown("<span class='bandeau-admin'>ADMINISTRATEUR</span>", unsafe_allow_html=True)
    st.markdown(f"**{u['nom_affiche']}**  \n<span class='petit'>{DB.ROLES[u['role']]}</span>", unsafe_allow_html=True)
    h = C.horloge()
    st.markdown(f"**{C.jour_long(C.maintenant().date())} — {C.maintenant():%H:%M}**")
    if h.get("mode") == "demo":
        st.markdown(C.badge("horloge de démonstration", "ambre"), unsafe_allow_html=True)
    if st.button("Se déconnecter", width="stretch"):
        C.tracer("déconnexion")
        st.session_state.clear()
        st.rerun()

pages = {
    "Bloc opératoire": [
        st.Page(accueil.afficher, title="Accueil", url_path="accueil", default=u["role"] != "admin"),
        st.Page(consultation.afficher, title="Consultation", url_path="consultation"),
        st.Page(planning.afficher, title="Planning", url_path="planning"),
        st.Page(urgences.afficher, title="Urgences", url_path="urgences"),
        st.Page(patients.afficher, title="Mes patients" if u["role"] == "chirurgien" else "Patients",
                url_path="patients"),
    ],
    "Compte": [st.Page(confidentialite.afficher, title="Confidentialité", url_path="confidentialite")],
}
if u["role"] == "admin":
    pages = {"Pilotage": [st.Page(dashboard.afficher, title="Tableau de bord", url_path="tableau-de-bord",
                                  default=True),
                          st.Page(historique.afficher, title="Historique", url_path="historique")], **pages}
    pages["Compte"].insert(0, st.Page(admin.afficher, title="Administration", url_path="admin"))

st.session_state["_pages"] = [p for groupe in pages.values() for p in groupe]
st.navigation(pages).run()
