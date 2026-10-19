# -*- coding: utf-8 -*-
"""
Métaheuristiques (une seule implémentation par algorithme : celle de l'hybridation, D3) : les références
RS / TABOU / AGS seuls et les modes hybrides ne sont jamais pires que le départ, le niveau 1 est sans conflit,
l'état incrémental donne exactement la fonction objectif, et les modes de calcul du programme du site fonctionnent.
"""
import contextlib
import io
import random

import pytest

from aide import LUNDI
from orchestre import chemins
from orchestre import programme as P

import structures_communes as SC

H = chemins.module("hybridage2")
REFERENCES = ["RS seul", "TABOU seul", "AGS seul"]


@pytest.fixture(scope="module")
def reference():
    return SC.instance_niveau2_reference()


def _executer(niveau, instance, mode):
    with contextlib.redirect_stdout(io.StringIO()):
        return H._executer_niveau(niveau, instance, [mode], 1.0, SC.GRAINE_ETUDE, H.ParametresRechercheLocale())[0]


@pytest.mark.parametrize("mode", REFERENCES)
def test_niveau1_ameliore_sans_conflit(reference, mode):
    inst1, _ = reference
    r = _executer(1, inst1, mode)
    assert r.score_final <= r.score_initial
    assert SC.verifier_solution_niveau1(inst1, SC.SolutionPlanning(r.solution)) == []


@pytest.mark.parametrize("mode", REFERENCES)
def test_niveau2_jamais_pire_que_le_glouton(reference, mode):
    _, inst2 = reference
    r = _executer(2, inst2, mode)
    assert r.score_final <= r.score_initial
    assert r.nb_evaluations > 0


def test_l_etat_incremental_egale_la_fonction_objectif(reference):
    _, inst2 = reference
    rng, compat = random.Random(0), {p: SC.vacations_compatibles(q, inst2.vacations) for p, q in inst2.patients.items()}
    for _ in range(10):
        aff = {p: rng.choice(c) if c else None for p, c in compat.items()}
        assert SC.EtatNiveau2(inst2, aff).score() == pytest.approx(
            SC.evaluer_niveau2(inst2, SC.SolutionPatients(aff)).score_total)


@pytest.mark.parametrize("mode", ["glouton"] + REFERENCES)
def test_modes_de_calcul_du_programme(mode):
    prog = P.calculer_programme(LUNDI, mode, 1.0)
    glouton = SC.evaluer_niveau2(prog.instance2, SC.construire_meilleure_affectation_initiale(prog.instance2)).score_total
    assert prog.solution.non_places() == []
    assert SC.evaluer_niveau2(prog.instance2, prog.solution).score_total <= glouton + 1e-6


@pytest.mark.lent
def test_mode_memetique_du_site():
    prog = P.calculer_programme(LUNDI, "memetique", 3.0)
    assert prog.solution.non_places() == [] and prog.resultat.score_final <= prog.score_glouton
