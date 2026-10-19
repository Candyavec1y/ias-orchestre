# -*- coding: utf-8 -*-
"""Panne du monte-lit : aucun patient hospitalisé ne monte au bloc pendant la panne ; fin de panne."""
from datetime import datetime, time, timedelta

from aide import MARDI, coherent, fin_panne, panne
from orchestre import sma_service as S

DEBUT, FIN = datetime.combine(MARDI, time(10, 15)), datetime.combine(MARDI, time(13, 0))


def _hospitalises_montes_pendant(sim, debut, fin):
    """Interventions de patients venant de leur chambre dont le brancardage tombe pendant [debut, fin[."""
    tr = timedelta(minutes=sim.modele.parametres.transfert_min)
    return [it for it in sim.interventions() if it.origine == "chambre" and it.debut > debut
            and it.debut - tr < fin and it.debut.date() == debut.date()]


def test_aucun_patient_hospitalise_brancarde_pendant_la_panne(prog):
    sim = S.simuler(prog, [panne(DEBUT, FIN)], datetime.combine(MARDI, time(18)))
    assert _hospitalises_montes_pendant(sim, DEBUT, FIN) == []
    assert coherent(sim) == []


def test_fin_de_panne_anticipee(prog):
    reparation = DEBUT + timedelta(hours=1)
    sim = S.simuler(prog, [panne(DEBUT, FIN), fin_panne(reparation)], datetime.combine(MARDI, time(18)))
    assert sim.pannes() == {}
    assert _hospitalises_montes_pendant(sim, DEBUT, reparation) == []
    assert coherent(sim) == []


def test_la_logistique_constate_seule_la_fin_de_panne_estimee(prog):
    sim = S.simuler(prog, [panne(DEBUT, FIN)], FIN + timedelta(minutes=10))
    assert sim.pannes() == {}
