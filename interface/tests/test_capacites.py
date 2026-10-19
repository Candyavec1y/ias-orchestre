# -*- coding: utf-8 -*-
"""Capacités d'hébergement : un patient programmé ne prend jamais un lit au-delà de la capacité ; réserve d'urgence."""
from datetime import datetime, time, timedelta

from aide import LUNDI, MARDI, MATIN, coherent, inscription, patient, urgence
from orchestre import programme as P
from orchestre import sma_service as S

import structures_communes as SC

PETITE = SC.ParametresHebergement(lits_disponibles_par_jour=12, places_ambulatoires_par_jour=20, reserve_lits=2)


def _occupation_lits(sim):
    return sim.modele.hebergement.occupation()[0]


def test_les_inscriptions_respectent_les_lits_programmables():
    prog = P.calculer_programme(LUNDI, "glouton", hebergement=PETITE)
    avant = _occupation_lits(S.simuler(prog, [], MATIN))
    patients = [patient(k, ambulatoire=False, nuits_post_op=3) for k in range(25)]
    sim = S.simuler(prog, [inscription(MATIN + timedelta(seconds=k), p) for k, p in enumerate(patients)],
                    MATIN + timedelta(minutes=5))
    apres = _occupation_lits(sim)
    assert all(apres[j] <= max(PETITE.cap_lits, avant.get(j, 0)) for j in apres)
    assert sim.en_attente() == [] and coherent(sim) == []


def test_une_urgence_peut_utiliser_la_reserve():
    prog = P.calculer_programme(LUNDI, "glouton", hebergement=PETITE)
    t = datetime.combine(MARDI, time(9))
    evts = [urgence(t + timedelta(minutes=5 * n), n) for n in range(1, 9)]
    sim = S.simuler(prog, evts, t + timedelta(hours=10))
    assert sim.modele.bilan()["urgences_non_programmees"] == 0


def test_capacites_reglees_par_l_administrateur(base_isolee):
    from orchestre import stockage as DB
    from vues import commun as C
    assert C.hebergement() == SC.HEBERGEMENT_SITE
    DB.ecrire_parametre("hebergement", {"lits_disponibles_par_jour": 42, "places_ambulatoires_par_jour": 18,
                                        "reserve_lits": 4})
    h = C.hebergement()
    assert (h.cap_lits, h.cap_places, h.reserve_lits) == (38, 18, 4)
