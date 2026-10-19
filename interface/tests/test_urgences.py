# -*- coding: utf-8 -*-
"""Urgences : aucune n'est refusée, délais, planning de garde, interventions commencées intouchables, traçage."""
from datetime import date, datetime, time, timedelta

from aide import MARDI, coherent, etat, urgence
from orchestre import sma_service as S

NEUF_HEURES = datetime.combine(MARDI, time(9, 0))


def _decision(sim, n):
    pid = S.pid_urgence(n)
    return next(d for d in sim.decisions() if d.get("patient") == pid and d["type"] == "urgence")


def test_urgence_urgente_prise_en_charge_dans_le_delai(prog):
    sim = S.simuler(prog, [urgence(NEUF_HEURES, 1, gravite="urgente")], NEUF_HEURES + timedelta(hours=8))
    d = _decision(sim, 1)
    assert d["dans_delai"] and not d["garde"]
    assert coherent(sim) == []


def test_urgence_vitale_dans_l_heure(prog):
    sim = S.simuler(prog, [urgence(NEUF_HEURES, 1, gravite="vitale")], NEUF_HEURES + timedelta(hours=4))
    d = _decision(sim, 1)
    assert d["dans_delai"] and d["attente_min"] <= S.GRAVITES["vitale"].delai_max_min


def test_aucune_urgence_refusee_meme_en_saturation(prog):
    evts = [urgence(NEUF_HEURES, n, gravite="vitale") for n in range(1, 16)]
    sim = S.simuler(prog, evts, NEUF_HEURES + timedelta(hours=20))
    b = sim.modele.bilan()
    assert b["urgences_recues"] == b["urgences_programmees"] == 15
    assert b["urgences_non_programmees"] == 0
    assert b["urgences_au_planning_de_garde"] >= 1
    assert any(a.startswith("GARDE") for a in sim.alertes())
    assert coherent(sim) == []


def test_tous_les_chirurgiens_du_service_sont_competents(prog):
    """Régression : le mercredi, les urgences vues par le Dr CT partaient en garde malgré les vacations libres."""
    mercredi = datetime.combine(MARDI + timedelta(days=1), time(9, 40))
    evts = [urgence(mercredi, n, chirurgien="CT") for n in range(1, 6)]
    sim = S.simuler(prog, evts, mercredi + timedelta(hours=10))
    decisions = [_decision(sim, n) for n in range(1, 6)]
    assert not any(d["garde"] for d in decisions)
    assert all(d["dans_delai"] for d in decisions)


def test_une_intervention_commencee_n_est_jamais_deplacee(prog):
    dix_heures = datetime.combine(MARDI, time(10, 0))
    avant = S.simuler(prog, [], dix_heures)
    commencees = {it.pid: (it.salle_id, it.debut) for it in avant.interventions() if it.debut < dix_heures}
    sim = S.simuler(prog, [urgence(dix_heures, n) for n in range(1, 7)], dix_heures + timedelta(hours=6))
    apres = {it.pid: (it.salle_id, it.debut) for it in sim.interventions()}
    assert all(apres.get(pid) == e for pid, e in commencees.items())


def test_le_programme_est_photographie_avant_et_apres_chaque_urgence(prog):
    evts = [urgence(NEUF_HEURES, 1), urgence(NEUF_HEURES + timedelta(minutes=5), 2)]
    sim = S.simuler(prog, evts, NEUF_HEURES + timedelta(hours=6))
    for n in (1, 2):
        avant, apres = sim.modele.traces_urgences[S.pid_urgence(n)]
        assert S.pid_urgence(n) not in avant and apres[S.pid_urgence(n)][0] == "programmé"


def test_les_alertes_sont_horodatees_a_l_heure_de_l_evenement(prog):
    evts = [urgence(NEUF_HEURES, n, gravite="vitale") for n in range(1, 16)]
    sim = S.simuler(prog, evts, NEUF_HEURES + timedelta(hours=20))
    assert sim.alertes_horodatees()
    assert all(h == NEUF_HEURES for h, _ in sim.alertes_horodatees())


def test_rejeu_deterministe(prog):
    evts = [urgence(NEUF_HEURES + timedelta(minutes=10 * n), n) for n in range(1, 6)]
    fin = NEUF_HEURES + timedelta(hours=8)
    assert etat(S.simuler(prog, evts, fin)) == etat(S.simuler(prog, evts, fin))


def test_la_garde_n_opere_qu_aux_heures_de_garde_hors_vitales(prog):
    evts = [urgence(NEUF_HEURES, n, gravite="urgente") for n in range(1, 25)]
    sim = S.simuler(prog, evts, datetime.combine(date(2026, 10, 14), time(8)))
    garde = sim.modele.garde
    assert all(garde.en_garde(it.debut, it.gravite) for it in garde.interventions.values())
    assert coherent(sim) == []
