# -*- coding: utf-8 -*-
"""Métaheuristiques : jamais pire que le départ, niveau 1 sans conflit, modes de calcul du programme du site."""
import importlib.util
import random

import pytest

from aide import LUNDI
from orchestre import chemins
from orchestre import programme as P

import structures_communes as SC


def _module(nom: str, fichier: str):
    spec = importlib.util.spec_from_file_location(nom, chemins.RACINE / "metaheuristiques" / fichier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGS = _module("algorithme_genetique", "algorithme_genetique.py")
RS = _module("recuit_simule_test", "recuit_simulé.py")


@pytest.fixture(scope="module")
def reference():
    return SC.instance_niveau2_reference()


@pytest.mark.parametrize("algo", [AGS, RS], ids=["AGS", "RS"])
def test_niveau1_ameliore_sans_conflit(reference, algo):
    inst1, _ = reference
    r = algo.resoudre_niveau1(inst1)
    assert r.score_final <= r.score_initial
    assert SC.verifier_solution_niveau1(inst1, SC.SolutionPlanning(r.solution)) == []


@pytest.mark.parametrize("algo", [AGS, RS], ids=["AGS", "RS"])
def test_niveau2_jamais_pire_que_le_glouton(reference, algo):
    _, inst2 = reference
    r = algo.resoudre_niveau2(inst2)
    assert r.score_final <= r.score_initial
    assert r.historique and r.nb_evaluations > 0


def test_ags_le_score_rapide_egale_la_fonction_objectif(reference):
    _, inst2 = reference
    pb, rng = AGS.ProblemeGenetiqueNiveau2(inst2), random.Random(0)
    for _ in range(10):
        ind = pb.individu_aleatoire(rng)
        assert pb.cout(ind) == pytest.approx(SC.evaluer_niveau2(inst2, pb.vers_solution(ind)).score_total)


@pytest.mark.parametrize("mode", ["glouton", "algorithme_genetique.py", "recuit_simule.py"])
def test_modes_de_calcul_du_programme(mode):
    prog = P.calculer_programme(LUNDI, mode)
    glouton = SC.evaluer_niveau2(prog.instance2, SC.construire_meilleure_affectation_initiale(prog.instance2)).score_total
    assert prog.solution.non_places() == []
    assert SC.evaluer_niveau2(prog.instance2, prog.solution).score_total <= glouton + 1e-6


@pytest.mark.lent
def test_mode_memetique_du_site():
    prog = P.calculer_programme(LUNDI, "memetique", 3.0)
    assert prog.solution.non_places() == [] and prog.resultat.score_final <= prog.score_glouton
