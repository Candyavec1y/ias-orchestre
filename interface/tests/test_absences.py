# -*- coding: utf-8 -*-
"""Absence d'un chirurgien : vacations fermées, patients replacés, prévenance, confrère seulement s'il est accepté."""
from datetime import datetime, time, timedelta

from aide import LUNDI, MATIN, absence, coherent, inscription, patient, urgence
from orchestre import sma_service as S

CT = S.id_chirurgien("CT")
DU, AU = LUNDI + timedelta(weeks=2), LUNDI + timedelta(weeks=2, days=4)     # 26/10 -> 30/10
DECLARATION = MATIN + timedelta(days=7)                                      # déclarée le lundi 19/10


def _pendant(it) -> bool:
    return DU <= it.debut.date() <= AU


def test_vacations_fermees_et_patients_replaces(prog):
    avant = S.simuler(prog, [], DECLARATION)
    concernes = {it.pid for it in avant.interventions() if it.chirurgien_id == CT and _pendant(it)}
    assert concernes, "le scénario doit toucher des patients"
    sim = S.simuler(prog, [absence(DECLARATION, "CT", DU, AU)], DECLARATION + timedelta(minutes=1))
    assert not [it for it in sim.interventions() if it.chirurgien_id == CT and _pendant(it)]
    assert all(sim.intervention(pid) is not None for pid in concernes)
    assert sim.en_attente() == [] and coherent(sim) == []
    fenetres = [f for s in sim.modele.salles.values() for f in s.creneaux.values()
                if f.chirurgien_id == CT and DU <= f.jour <= AU]
    assert fenetres and all(sim.modele.fenetre_fermee(f) for f in fenetres)


def test_patients_sans_consentement_restent_chez_leur_chirurgien_avec_prevenance(prog):
    avant = S.simuler(prog, [], DECLARATION)
    concernes = [it.pid for it in avant.interventions() if it.chirurgien_id == CT and _pendant(it)]
    sim = S.simuler(prog, [absence(DECLARATION, "CT", DU, AU)], DECLARATION + timedelta(minutes=1))
    for pid in concernes:
        it = sim.intervention(pid)
        assert it.chirurgien_id == CT
        assert it.debut.date() >= DECLARATION.date() + timedelta(days=S.SMA.ParametresSMA().prevenance_absence_jours)


def test_patient_ayant_accepte_un_confrere_peut_etre_opere_pendant_l_absence(prog):
    p = patient(1, date_min=DU)
    evts = [inscription(MATIN, p, confrere=True), absence(DECLARATION, "CT", DU, AU)]
    sim = S.simuler(prog, evts, DECLARATION + timedelta(minutes=1))
    it = sim.intervention(p.id)
    assert it is not None and (it.chirurgien_id != CT or it.debut.date() > AU)


def test_consultation_pendant_l_absence_aucune_proposition_dans_la_periode(prog):
    sim = S.simuler(prog, [absence(DECLARATION, "CT", DU, AU)], DECLARATION + timedelta(minutes=1))
    props = S.proposer_creneaux(sim, patient(2, date_min=DU), DU, accepter_confrere=False)
    assert props and all(p["jour"] > AU for p in props)


def test_urgence_pendant_l_absence_jamais_operee_par_le_chirurgien_absent(prog):
    t = datetime.combine(DU + timedelta(days=1), time(9))                   # mardi : le Dr CT opère d'habitude
    evts = [absence(DECLARATION, "CT", DU, AU), urgence(t, 1, chirurgien="CT")]
    sim = S.simuler(prog, evts, t + timedelta(hours=8))
    assert sim.intervention(S.pid_urgence(1)).chirurgien_id != CT
    assert coherent(sim) == []


def test_retour_anticipe_ne_deplace_que_les_patients_de_la_periode_courte(prog):
    avant = S.simuler(prog, [], DECLARATION)
    fin_courte = DU + timedelta(days=1)
    hors_periode = {it.pid: (it.salle_id, it.debut) for it in avant.interventions()
                    if it.chirurgien_id == CT and fin_courte < it.debut.date() <= AU}
    assert hors_periode, "le scénario doit avoir des patients après le retour anticipé"
    sim = S.simuler(prog, [absence(DECLARATION, "CT", DU, fin_courte)], DECLARATION + timedelta(minutes=1))
    assert {pid: (sim.intervention(pid).salle_id, sim.intervention(pid).debut) for pid in hors_periode} == hors_periode


def test_alerte_pour_chaque_patient_prioritaire_repousse_de_plus_de_3_jours(prog):
    # déclarée le samedi précédent : avec 2 jours de prévenance, personne ne peut être avancé avant le départ
    samedi = datetime.combine(DU - timedelta(days=2), time(8))
    avant = {it.pid: it.debut.date() for it in S.simuler(prog, [], samedi).interventions()}
    sim = S.simuler(prog, [absence(samedi, "CT", DU, AU + timedelta(days=7))], samedi + timedelta(minutes=1))
    attendues = {d["patient"] for d in sim.decisions() if d["type"] == "replacement" and d.get("motif") == "absence"
                 and sim.intervention(d["patient"]).patient.priorite >= 3
                 and (d["debut"].date() - avant[d["patient"]]).days > S.SMA.ParametresSMA().seuil_alerte_report_jours}
    signalees = {pid for pid in avant if any(f"P{pid} " in a and "repoussé" in a for a in sim.alertes())}
    assert attendues, "le scénario doit repousser au moins un patient prioritaire"
    assert signalees == attendues
