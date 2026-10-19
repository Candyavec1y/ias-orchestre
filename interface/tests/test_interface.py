# -*- coding: utf-8 -*-
"""
Interface Streamlit sans navigateur (streamlit.testing.AppTest), sur une base isolée : connexion, chaque page pour
chaque rôle, onglets selon le rôle, déclaration d'une urgence et d'une absence, alertes temporaires.
"""
from datetime import date, datetime, timedelta

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from orchestre import chemins
from orchestre import stockage as DB

MDP = "Mot-de-passe-2026!"
COMPTES = {"admin": ("admin", "Administrateur", ""), "regulation": ("regulation", "Cadre de bloc", ""),
           "dr.ct": ("chirurgien", "Dr CT", "CT"), "dr.cl": ("chirurgien", "Dr CL", "CL")}
HORLOGE = datetime(2026, 10, 14, 10, 0)
PAGES = {"admin": ["accueil", "consultation", "planning", "urgences", "patients", "dashboard", "historique", "admin",
                   "confidentialite"],
         "regulation": ["accueil", "consultation", "planning", "urgences", "patients", "confidentialite"],
         "dr.ct": ["accueil", "consultation", "planning", "urgences", "patients", "confidentialite"]}


@pytest.fixture
def site(base_isolee, prog):
    from vues import commun as C
    st.cache_resource.clear()
    for login, (role, nom, prat) in COMPTES.items():
        DB.creer_utilisateur(login, MDP, role, nom, prat)
    C.enregistrer_programme(prog, "test")
    C.regler_horloge(HORLOGE)
    yield C
    st.cache_resource.clear()


def page(nom: str, login: str) -> AppTest:
    role, nom_affiche, prat = COMPTES[login]
    return AppTest.from_string(f"""
import streamlit as st
from vues import commun as C, {nom}
C.charger_planning_vacations()
st.session_state["utilisateur"] = {{"login": {login!r}, "nom_affiche": {nom_affiche!r}, "role": {role!r},
                                    "praticien": {prat!r}, "doit_changer": False}}
{nom}.afficher()
""", default_timeout=300).run()


def _bouton(at: AppTest, libelle: str):
    return next(b for b in at.button if b.label.startswith(libelle))


@pytest.mark.parametrize("login,nom", [(l, p) for l, pages in PAGES.items() for p in pages])
def test_chaque_page_s_affiche_pour_chaque_role(site, login, nom):
    at = page(nom, login)
    assert [e.value for e in at.exception] == []


def test_connexion(site):
    at = AppTest.from_file(str(chemins.DOSSIER_INTERFACE / "app.py"), default_timeout=300).run()
    at.text_input[0].set_value("dr.ct"); at.text_input[1].set_value("mauvais")
    at.button[0].click().run()
    assert any("incorrect" in e.value for e in at.error)
    at.text_input[0].set_value("dr.ct"); at.text_input[1].set_value(MDP)
    at.button[0].click().run()
    assert at.session_state["utilisateur"]["login"] == "dr.ct" and not at.exception


def test_onglets_selon_le_role(site):
    assert [t.label for t in page("urgences", "dr.ct").tabs] == ["Déclarer une urgence", "Incident logistique",
                                                                 "Mes absences"]
    assert "Absence d'un chirurgien" in [t.label for t in page("urgences", "regulation").tabs]
    assert "Bloc" not in [t.label for t in page("planning", "admin").tabs]
    assert "Bloc" in [t.label for t in page("planning", "regulation").tabs]
    assert [t.label for t in page("admin", "admin").tabs] == ["Comptes", "Planning des vacations", "Lits et places",
                                                              "Optimisation globale", "Horloge"]


def test_declarer_une_urgence(site):
    at = page("urgences", "regulation")
    next(r for r in at.radio if r.label == "Gravité").set_value("urgente")
    _bouton(at, "Déclarer l'urgence").click().run()
    assert not at.exception
    assert any(m.value.startswith("URG-") for m in list(at.success) + list(at.warning))
    assert [e["type"] for e in DB.lister_evenements()] == ["urgence"]


def test_un_chirurgien_declare_sa_propre_absence_et_ne_voit_pas_celle_des_autres(site):
    at = page("urgences", "dr.ct")
    assert next(t for t in at.text_input if t.label == "Chirurgien").disabled
    next(d for d in at.date_input if d.label == "Du").set_value(date(2026, 11, 16))
    next(d for d in at.date_input if d.label == "Au (inclus)").set_value(date(2026, 11, 20))
    _bouton(at, "Déclarer l'absence").click().run()
    assert any("Dr CT" in m.value for m in at.success)
    assert [e["contenu"]["praticien"] for e in DB.lister_evenements()] == ["CT"]
    autre = page("urgences", "dr.cl")
    assert not any("Chirurgien" in d.value.columns for d in autre.dataframe)


def test_une_alerte_disparait_du_bandeau_apres_10_minutes(site):
    at = page("urgences", "regulation")
    next(r for r in at.radio if r.label == "Gravité").set_value("vitale")
    for _ in range(12):                                                    # sature la plage d'urgence : alerte
        _bouton(at, "Déclarer l'urgence").click().run()
    assert page("urgences", "regulation").error, "alerte visible juste après"
    site.regler_horloge(HORLOGE + timedelta(minutes=11))
    at = page("urgences", "regulation")
    assert not at.error
    assert any(x.label.startswith("Alertes du jour") for x in at.expander)
