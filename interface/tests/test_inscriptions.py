# -*- coding: utf-8 -*-
"""Inscription d'un patient de consultation : placement par le SMA, ordre d'arrivée, confrère, liste d'attente."""
from datetime import timedelta

from aide import LUNDI, MATIN, annulation, coherent, etat, inscription, patient
from orchestre import sma_service as S


def _simuler(prog, evts, minutes_apres=60):
    return S.simuler(prog, evts, MATIN + timedelta(minutes=minutes_apres))


def test_proposer_creneaux_ne_modifie_pas_le_programme(prog):
    sim = _simuler(prog, [])
    avant, n_messages = etat(sim), len(sim.modele.journal)
    props = S.proposer_creneaux(sim, patient(1), LUNDI)
    assert props, "au moins une proposition"
    assert etat(sim) == avant and len(sim.modele.journal) == n_messages


def test_nouveau_patient_place_apres_les_patients_deja_prevus(prog):
    avant = etat(_simuler(prog, []))
    p = patient(1)
    sim = _simuler(prog, [inscription(MATIN, p)])
    it = sim.intervention(p.id)
    assert it is not None
    meme_creneau = sim.modele.salles[it.salle_id].du_creneau(it.fenetre_id)
    assert all(i.debut < it.debut for i in meme_creneau if i.pid != p.id)
    deplaces = {pid for pid, e in etat(sim).items() if pid != p.id and avant.get(pid) != e}
    assert not deplaces, "une inscription ne déplace aucun autre patient"
    assert coherent(sim) == []


def test_creneau_choisi_par_le_chirurgien_est_respecte(prog):
    p = patient(1)
    choix = S.proposer_creneaux(_simuler(prog, []), p, LUNDI)[1]          # pas forcément le premier
    it = _simuler(prog, [inscription(MATIN, p, proposition=choix)]).intervention(p.id)
    assert (it.salle_id, it.fenetre_id) == (choix["salle_id"], choix["fenetre_id"])


def test_ordre_d_arrivee_respecte_a_priorite_egale(prog):
    patients = [patient(k, duree=120) for k in range(15)]
    evts = [inscription(MATIN + timedelta(seconds=k), p) for k, p in enumerate(patients)]
    sim = _simuler(prog, evts)
    debuts = [sim.intervention(p.id).debut for p in patients]
    assert debuts == sorted(debuts)
    assert all(sim.intervention(p.id).chirurgien_id == p.chirurgien_id for p in patients)
    assert coherent(sim) == []


def test_confrere_refuse_le_patient_reste_chez_son_chirurgien_meme_apres_relance(prog):
    """Régression : la relance de la liste d'attente ignorait le refus d'un confrère."""
    patients = [patient(k, duree=120) for k in range(20)]
    evts = [inscription(MATIN + timedelta(seconds=k), p) for k, p in enumerate(patients)]
    sim = S.simuler(prog, evts, MATIN + timedelta(days=2))                # deux relances matinales
    assert all(sim.intervention(p.id).chirurgien_id == p.chirurgien_id for p in patients)


def test_confrere_accepte_permet_un_creneau_plus_tot(prog):
    patients = [patient(k, duree=120) for k in range(20)]
    def dernier(confrere):
        evts = [inscription(MATIN + timedelta(seconds=k), p, confrere=confrere) for k, p in enumerate(patients)]
        sim = _simuler(prog, evts)
        return max(sim.intervention(p.id).debut for p in patients), sim
    sans, _ = dernier(False)
    avec, sim = dernier(True)
    assert avec <= sans
    assert any(sim.intervention(p.id).chirurgien_id != p.chirurgien_id for p in patients)


def test_date_au_plus_tot_respectee(prog):
    p = patient(1, date_min=LUNDI + timedelta(days=16))
    it = _simuler(prog, [inscription(MATIN, p)]).intervention(p.id)
    assert it.debut.date() >= p.date_min


def test_plus_de_liste_d_attente_le_planning_est_connu_sur_un_an(prog):
    patients = [patient(k, duree=150) for k in range(60)]                 # bien plus que les vacations du mois
    evts = [inscription(MATIN + timedelta(seconds=k), p) for k, p in enumerate(patients)]
    sim = _simuler(prog, evts)
    assert sim.en_attente() == []
    assert max(sim.intervention(p.id).debut for p in patients).date() > LUNDI + timedelta(weeks=4)
    assert coherent(sim) == []


def test_liste_d_attente_seulement_sans_vacation_compatible(prog):
    p = patient(1, duree=600)                                              # plus long que toute vacation
    sim = _simuler(prog, [inscription(MATIN, p)])
    assert sim.intervention(p.id) is None
    assert [it.pid for it, _ in sim.en_attente()] == [p.id]


def test_annulation_libere_le_creneau(prog):
    p = patient(1)
    sim = _simuler(prog, [inscription(MATIN, p), annulation(MATIN + timedelta(minutes=5), p.id)])
    assert sim.intervention(p.id) is None and coherent(sim) == []


def test_l_heure_initiale_est_celle_du_premier_placement(prog):
    p = patient(1)
    sim = _simuler(prog, [inscription(MATIN, p)])
    it = sim.intervention(p.id)
    assert it.debut_initial == it.debut and it.debut_initial.hour >= 7
