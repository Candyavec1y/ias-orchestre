# -*- coding: utf-8 -*-
"""
Nouveaux aléas du SMA (lot 8 du nettoyage) : prolongation d'une intervention, indisponibilité de lits, transfert
proposé d'une urgence d'une spécialité non couverte.
"""
from datetime import datetime, time, timedelta

import pytest

from aide import MARDI, MATIN, coherent, indisponibilite_lits, panne, prolongation, urgence
from orchestre import sma_service as S

import sma_urgences as SMA
from structures_communes import jours_occupation

NEUF_HEURES = datetime.combine(MARDI, time(9))


# ---------------------------------------------------------------------------------------------------- prolongation
def _premier_avec_suivants(prog, t):
    """Intervention du mardi, non terminée à `t`, suivie d'au moins deux patients dans son créneau."""
    sim = S.simuler(prog, [], t)
    for s in sim.modele.salles.values():
        for f in s.creneaux.values():
            its = s.du_creneau(f.id)
            if f.jour == MARDI and len(its) >= 3 and its[0].fin > t:
                return sim, s, f, its
    pytest.skip("aucun créneau adapté")


def test_prolongation_decale_simplement_la_suite_du_creneau(prog):
    sim0, s, f, its = _premier_avec_suivants(prog, NEUF_HEURES)
    marge = (f.fin - its[-1].fin).total_seconds() / 60
    extra = max(5, int(marge // 2))
    sim = S.simuler(prog, [prolongation(NEUF_HEURES, its[0].pid, extra)], NEUF_HEURES + timedelta(minutes=1))
    apres = [sim.intervention(i.pid) for i in its]
    assert apres[0].fin - its[0].fin == timedelta(minutes=extra)
    assert all(a is not None and a.fenetre_id == f.id for a in apres)            # personne n'est déprogrammé
    assert all(a.debut >= i.debut for a, i in zip(apres[1:], its[1:]))            # personne n'est avancé
    assert coherent(sim) == []


def test_prolongation_au_dela_du_creneau_deprogramme_et_replace(prog):
    _, s, f, its = _premier_avec_suivants(prog, NEUF_HEURES)
    sim = S.simuler(prog, [prolongation(NEUF_HEURES, its[0].pid, 240)], NEUF_HEURES + timedelta(minutes=1))
    deplaces = [i for i in its[1:] if sim.intervention(i.pid).fenetre_id != f.id]
    assert deplaces, "la suite du créneau ne tient plus : des patients sont replacés ailleurs"
    assert all(sim.intervention(i.pid) is not None for i in its) and sim.en_attente() == []
    assert all(sim.intervention(i.pid).fin <= f.fin for i in its[1:] if sim.intervention(i.pid).fenetre_id == f.id)
    assert coherent(sim) == []


def test_prolongation_pendant_une_panne(prog):
    _, s, f, its = _premier_avec_suivants(prog, NEUF_HEURES)
    debut, fin = NEUF_HEURES - timedelta(minutes=30), NEUF_HEURES + timedelta(hours=3)
    sim = S.simuler(prog, [panne(debut, fin), prolongation(NEUF_HEURES, its[0].pid, 60)], NEUF_HEURES + timedelta(hours=8))
    tr = timedelta(minutes=sim.modele.parametres.transfert_min)
    montes = [it for it in sim.interventions() if it.origine == "chambre" and it.debut > debut
              and it.debut - tr < fin and it.debut.date() == MARDI]
    assert montes == [] and coherent(sim) == []


# ---------------------------------------------------------------------------------------------------- lits
JOUR = MARDI + timedelta(days=1)                                                # mercredi


def _hospitalises_du_jour(sim, jour):
    return {it.pid: it for it in sim.modele.interventions() if not it.urgence and not it.patient.ambulatoire
            and jour in jours_occupation(it.patient, it.debut.date())}


def test_la_capacite_reduite_n_est_jamais_depassee_par_la_programmation(prog):
    avant = S.simuler(prog, [], MATIN)
    occupes = avant.modele.hebergement.occupation()[0].get(JOUR, 0)
    h = SMA.HEBERGEMENT_SITE
    fermes = h.lits_disponibles_par_jour - h.reserve_lits - (occupes - 2)          # 2 lits de moins qu'occupés
    sim = S.simuler(prog, [indisponibilite_lits(MATIN, fermes, JOUR, JOUR)], MATIN + timedelta(minutes=1))
    heb = sim.modele.hebergement
    assert heb.occupation()[0].get(JOUR, 0) <= heb.cap_lits_jour(JOUR)
    assert heb.cap_lits_jour(JOUR + timedelta(days=1)) == SMA.HEBERGEMENT_SITE.cap_lits      # retour à la normale
    assert coherent(sim) == [] and sim.en_attente() == []


def test_les_patients_de_plus_faible_priorite_sont_deplaces_en_premier(prog):
    avant = S.simuler(prog, [], MATIN)
    presents = _hospitalises_du_jour(avant, JOUR)
    h = SMA.HEBERGEMENT_SITE
    fermes = h.lits_disponibles_par_jour - h.reserve_lits - len(presents) // 2      # la moitié des lits occupés
    sim = S.simuler(prog, [indisponibilite_lits(MATIN, fermes, JOUR, JOUR)], MATIN + timedelta(minutes=1))
    restes = _hospitalises_du_jour(sim, JOUR)
    deplaces = [it for pid, it in presents.items() if pid not in restes]
    gardes = [it for pid, it in presents.items() if pid in restes]
    assert deplaces and gardes
    assert max(it.patient.priorite for it in deplaces) <= min(it.patient.priorite for it in gardes)


def test_les_urgences_gardent_la_reserve_pendant_l_indisponibilite(prog):
    h = SMA.HEBERGEMENT_SITE
    fermes = h.lits_disponibles_par_jour - h.reserve_lits                           # aucun lit programmable
    arrivee = datetime.combine(JOUR, time(8))
    sim = S.simuler(prog, [indisponibilite_lits(MATIN, fermes, JOUR, JOUR),
                           urgence(arrivee, 1, gravite="vitale")], arrivee + timedelta(hours=4))
    d = next(d for d in sim.decisions() if d["type"] == "urgence")
    assert d["debut"].date() == JOUR and sim.modele.hebergement.cap_lits_jour(JOUR) == 0
    assert coherent(sim) == []


# ---------------------------------------------------------------------------------------------------- transfert
MERCREDI_9H = NEUF_HEURES + timedelta(days=1)                                  # le Dr CT n'opère pas le mercredi


def _urgence_sma(prog, specialite, gravite="vitale"):
    m = S.construire_modele(prog)
    p = SMA.patient_urgent(S.pid_urgence(1), S.id_chirurgien("CT"), 60, specialite=specialite, nuits_post_op=2)
    m.planifier(SMA.ArriveeUrgence(MERCREDI_9H, p, gravite=gravite))
    m.executer_jusqu_a(MERCREDI_9H + timedelta(hours=10))
    return m, p


def test_une_specialite_non_couverte_sans_chirurgien_a_temps_est_proposee_au_transfert(prog):
    m, p = _urgence_sma(prog, "Neurochirurgie")
    assert any(d["type"] == "urgence_transferee" and d["patient"] == p.id for d in m.regulation.decisions)
    assert any("transfert proposé" in a and f"P{p.id}" in a for a in m.regulation.alertes)
    assert m.bilan()["urgences_transferees"] == 1
    assert m.verifier_coherence() == []                                            # le SMA ne transfère pas seul


def test_dans_les_autres_cas_le_comportement_est_inchange(prog):
    m, p = _urgence_sma(prog, SMA.SPECIALITE_SERVICE)
    assert not any(d["type"] == "urgence_transferee" for d in m.regulation.decisions)
    d = next(d for d in m.regulation.decisions if d["type"] == "urgence" and d["patient"] == p.id)
    assert d["niveau"] < 5 and m.bilan()["urgences_transferees"] == 0
