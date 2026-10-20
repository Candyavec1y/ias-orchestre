# -*- coding: utf-8 -*-
"""
Validateur de faisabilité indépendant (commun/validation.py, D9) : une solution faisable connue est validée, chaque
type de contrainte violée volontairement est détecté, tolérance de dépassement des vacations, solution proposée =
meilleure solution faisable rencontrée, la sélection préfère une solution faisable, et le cas « aucune solution
faisable » est signalé.
"""
import contextlib
import io
from datetime import date, time, timedelta

import pytest

from aide import LUNDI
from orchestre import chemins
from orchestre import programme as P

import structures_communes as SC
import validation as VA
from sorties import ResultatMetaheuristique

H = chemins.module("hybridation")


def _types(v: VA.Validation) -> set[str]:
    return {x.type for x in v.violations}


# ---------------------------------------------------------------------------------------------------- niveau 1
@pytest.fixture
def mini_n1():
    """2 chirurgiens, 2 salles, 2 créneaux de 2 h ; le Dr B n'est disponible que sur le créneau 1."""
    j = LUNDI
    creneaux = {1: SC.Creneau(1, j, time(8), time(10)), 2: SC.Creneau(2, j, time(10), time(12))}
    plages = {11: SC.PlageBloc(11, 1, 1, "LIBRE"), 12: SC.PlageBloc(12, 1, 2, "LIBRE"),
              21: SC.PlageBloc(21, 2, 1, "LIBRE"), 22: SC.PlageBloc(22, 2, 2, "URGENCE")}
    chirurgiens = {1: SC.Chirurgien(1, "A", 4.0, (1, 2)), 2: SC.Chirurgien(2, "B", 2.0, (2,))}
    blocs = {1: SC.BlocAPlacer(1, 1), 2: SC.BlocAPlacer(2, 1), 3: SC.BlocAPlacer(3, 2)}
    inst = SC.InstanceProbleme(chirurgiens, {1: SC.Salle(1, "S1"), 2: SC.Salle(2, "S2")}, creneaux, plages, blocs,
                               {2: {1}})
    return inst, SC.SolutionPlanning({1: 11, 2: 12, 3: 21})                 # solution faisable


def test_n1_solution_faisable_validee(mini_n1):
    inst, sol = mini_n1
    assert VA.valider_niveau1(inst, sol).faisable


@pytest.mark.parametrize("modif,attendu", [
    ({1: None}, "bloc non affecté"),
    ({1: 99}, "plage inexistante"),
    ({3: 22}, "plage non disponible"),
    ({3: 11}, "salle non autorisée"),
    ({3: 21, 1: 21}, "conflit de salle"),
    ({2: 21}, "conflit de chirurgien"),
    ({3: 22}, "chirurgien indisponible"),
])
def test_n1_chaque_violation_est_detectee(mini_n1, modif, attendu):
    inst, sol = mini_n1
    aff = dict(sol.affectations)
    for b, p in modif.items():
        if p is None:
            aff.pop(b)
        else:
            aff[b] = p
    assert attendu in _types(VA.valider_niveau1(inst, SC.SolutionPlanning(aff)))


def test_n1_besoin_horaire_non_couvert(mini_n1):
    inst, sol = mini_n1
    plus = SC.InstanceProbleme(inst.chirurgiens | {1: SC.Chirurgien(1, "A", 6.0, (1, 2))}, inst.salles, inst.creneaux,
                               inst.plages_bloc, inst.blocs_a_placer, inst.disponibilites_chirurgiens)
    assert "besoin horaire non couvert" in _types(VA.valider_niveau1(plus, sol))


def test_n1_l_ancien_controle_et_le_validateur_concordent():
    inst1, _ = SC.instance_niveau2_reference()
    sol = SC.generer_solution_initiale_niveau1(inst1)
    assert VA.valider_niveau1(inst1, sol).faisable == (SC.verifier_solution_niveau1(inst1, sol) == [])


# ---------------------------------------------------------------------------------------------------- niveau 2
@pytest.fixture
def mini_n2():
    """1 vacation de 2 h (capacité utile 108 min), 1 lit et 1 place ambulatoire par jour."""
    j = LUNDI
    vacs = {1: SC.Vacation(1, 1, 1, j, time(8), time(10)), 2: SC.Vacation(2, 2, 1, j + timedelta(days=1), time(8),
                                                                             time(10))}
    patients = {1: SC.Patient(1, 1, 60, ambulatoire=False, nuits_post_op=1),
                2: SC.Patient(2, 1, 30, ambulatoire=True),
                3: SC.Patient(3, 2, 60, ambulatoire=True, date_min=j + timedelta(days=1))}
    inst = SC.InstanceNiveau2(patients, vacs, SC.ParametresHebergement(1, 1, 0))
    return inst, SC.SolutionPatients({1: 1, 2: 1, 3: 2})


def test_n2_solution_faisable_validee(mini_n2):
    inst, sol = mini_n2
    assert VA.valider_niveau2(inst, sol).faisable


def test_n2_chaque_violation_est_detectee(mini_n2):
    inst, sol = mini_n2
    cas = {"patient non affecté": {1: None}, "vacation inexistante": {1: 9}, "chirurgien incompatible": {1: 2}}
    for attendu, modif in cas.items():
        assert attendu in _types(VA.valider_niveau2(inst, SC.SolutionPatients({**sol.affectations, **modif})))
    tot = SC.InstanceNiveau2({**inst.patients, 3: SC.Patient(3, 2, 60, ambulatoire=True, date_min=LUNDI + timedelta(days=5))},
                             inst.vacations, inst.hebergement)
    assert "date au plus tôt" in _types(VA.valider_niveau2(tot, sol))
    longue = SC.InstanceNiveau2({**inst.patients, 2: SC.Patient(2, 1, 60, ambulatoire=True)}, inst.vacations,
                                inst.hebergement)
    assert "capacité de vacation" in _types(VA.valider_niveau2(longue, sol))
    deux_lits = SC.InstanceNiveau2({**inst.patients, 2: SC.Patient(2, 1, 30, ambulatoire=False)}, inst.vacations,
                                   inst.hebergement)
    assert "lits" in _types(VA.valider_niveau2(deux_lits, sol))
    deux_places = SC.InstanceNiveau2({**inst.patients, 3: SC.Patient(3, 1, 30, ambulatoire=True)}, inst.vacations,
                                     inst.hebergement)
    assert "places ambulatoires" in _types(VA.valider_niveau2(deux_places, SC.SolutionPatients({1: 1, 2: 1, 3: 1})))


def test_n2_tolerance_de_depassement_des_vacations(mini_n2):
    """Quelques minutes au-delà de la capacité utile restent faisables (TOLERANCE_DEPASSEMENT_VACATION_MIN), au-delà
    non ; l'état incrémental des métaheuristiques juge comme le validateur."""
    inst, sol = mini_n2
    tol = VA.TOLERANCE_DEPASSEMENT_VACATION_MIN
    for duree, attendu in ((108 - 60 + tol - 3, True), (108 - 60 + tol + 2, False)):     # 60 min déjà dans la vacation
        i2 = SC.InstanceNiveau2({**inst.patients, 2: SC.Patient(2, 1, duree, ambulatoire=True)}, inst.vacations,
                                inst.hebergement)
        assert VA.valider_niveau2(i2, sol).faisable is attendu
        assert SC.EtatNiveau2(i2, sol.affectations).faisable() is attendu


def test_n2_la_solution_proposee_est_la_meilleure_faisable_rencontree():
    """Règle de l'équipe : les dépassements ne sont que pénalisés pendant la recherche, mais la solution proposée
    est faisable dès qu'une solution faisable a été rencontrée (le départ de l'instance v28 ne l'est pas)."""
    inst = H.etendre_horizon(H.instance_v28(LUNDI, 4, charge=0.90), H.NB_SEMAINES_REPORT)
    for mode in ("TABOU seul", "RS seul"):
        with contextlib.redirect_stdout(io.StringIO()):
            r = H._executer_niveau(2, inst, [mode], 1.0, 1, H.ParametresRechercheLocale())[0]
        assert r.faisable, (mode, r.validation.get("par_type"))


def test_n2_le_programme_du_site_est_valide_pour_toutes_les_methodes():
    """Régression : les échanges de l'hybridation plaçaient des patients avant leur date au plus tôt."""
    for mode in ("glouton", "memetique", "RS seul", "TABOU seul", "AGS seul"):
        prog = P.calculer_programme(LUNDI, mode, 1.0)
        assert prog.validation["faisable"], (mode, prog.validation["par_type"])


# ---------------------------------------------------------------------------------------------------- sélection
def _resultat(mode, score, faisable):
    return ResultatMetaheuristique(algo="AGS+RS+TABOU", niveau=2, nom_instance="t", variante=mode, score_final=score,
                                   validation={"faisable": faisable, "par_type": {} if faisable else {"lits": 1},
                                               "violations": []})


def test_la_selection_prefere_une_solution_faisable():
    choix = H._meilleur_hybride([_resultat("memetique", 100, False), _resultat("AGS>RS>TABOU", 200, True)])
    assert choix.variante == "AGS>RS>TABOU"


def test_aucune_solution_faisable_est_signalee_et_marquee():
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        choix = H._meilleur_hybride([_resultat("memetique", 100, False), _resultat("AGS>RS>TABOU", 50, False)])
    assert choix.variante == "AGS>RS>TABOU" and not choix.faisable
    assert "NON VALIDE" in sortie.getvalue()


def test_toutes_les_methodes_ont_le_meme_depart_et_le_meme_budget():
    inst2 = H.instance_v28(LUNDI, 1)
    with contextlib.redirect_stdout(io.StringIO()):
        res = H._executer_niveau(2, inst2, list(H.MODES) + list(H.REFERENCES), 0.3, SC.GRAINE_ETUDE,
                                 H.ParametresRechercheLocale())
    assert len({r.score_initial for r in res}) == 1
    assert len({r.parametres["temps_max_s"] for r in res}) == 1
    assert all(r.validation and r.score_recherche is not None and "report" in r.detail_score for r in res)


def test_instance_v28_seul_le_nombre_de_patients_varie():
    a, b = H.instance_v28(LUNDI, 2, nb_patients=120), H.instance_v28(LUNDI, 2, charge=0.5)
    assert len(a.patients) == 120 and a.vacations.keys() == b.vacations.keys()
    assert a.hebergement == SC.HEBERGEMENT_SITE
    assert all(LUNDI <= v.jour < LUNDI + timedelta(weeks=2) for v in a.vacations.values())
    assert H.instance_v28(LUNDI, 1).patients.keys() == H.instance_v28(LUNDI, 1).patients.keys()   # déterministe
    assert date(2026, 10, 12) == LUNDI
