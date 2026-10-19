# -*- coding: utf-8 -*-
"""Étude de saturation (saturation.py) : sanité des mesures sur une semaine ; l'étude complète est marquée « lent »."""
import pytest

from saturation import etudier


@pytest.fixture(scope="module")
def une_semaine():
    return etudier(semaines=1, analyser_ressources=False)


def test_les_mesures_sont_coherentes(une_semaine):
    r = une_semaine
    assert r.erreurs_coherence == 0
    assert 0 < r.places_dans_horizon < r.n_patients
    assert r.occupation_utile_pct <= 100.5                    # la marge de 10 % des créneaux futurs est respectée
    assert r.occupation_finale_pct <= r.occupation_utile_pct


def test_la_courbe_d_occupation_est_croissante(une_semaine):
    valeurs = [o for _, o in une_semaine.courbe]
    assert valeurs == sorted(valeurs) and valeurs[-1] == pytest.approx(une_semaine.occupation_finale_pct)


def test_au_dela_de_la_capacite_les_patients_debordent(une_semaine):
    assert une_semaine.premier_debordement is not None
    assert une_semaine.seuils[50] is not None and une_semaine.seuils[50] < une_semaine.places_dans_horizon


@pytest.mark.lent
def test_etude_complete_quatre_semaines():
    r = etudier(semaines=4)
    assert r.erreurs_coherence == 0 and r.ressource_limitante
    assert 300 < r.places_dans_horizon < 700
