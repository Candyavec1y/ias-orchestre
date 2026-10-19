# -*- coding: utf-8 -*-
"""
Convention d'occupation (Q13). Lits : sortie à midi, lit réutilisable le jour même après remise en état, jamais
deux patients à la fois dans un lit. Places ambulatoires : par demi-journée, une place sert le matin puis
l'après-midi après remise en état. Même décompte dans le niveau 2, le SMA, les indicateurs et le validateur.
"""
from datetime import time, timedelta

from aide import LUNDI, MATIN
from orchestre import programme as P
from orchestre import sma_service as S

import parametres as P_
import structures_communes as SC
import validation as VA
from sorties import calculer_indicateurs_niveau2

MARDI, MERCREDI, JEUDI = (LUNDI + timedelta(days=k) for k in (1, 2, 3))
HUIT_HEURES, QUATORZE_HEURES = time(8), time(14)


def _hospitalise(pid, nuits_avant=0, nuits_apres=2, chirurgien=1):
    return SC.Patient(pid, chirurgien, 60, ambulatoire=False, nuits_pre_op=nuits_avant, nuits_post_op=nuits_apres)


def _ambulatoire(pid, chirurgien=1):
    return SC.Patient(pid, chirurgien, 60, ambulatoire=True)


def _instance(patients, lits=1, places=5):
    """Vacations 0-4 : le matin du lundi au vendredi ; 5 : lundi après-midi."""
    vacs = {k: SC.Vacation(k, 1, 1, LUNDI + timedelta(days=k), time(8), time(13)) for k in range(5)}
    vacs[5] = SC.Vacation(5, 1, 1, LUNDI, time(13, 30), time(17, 30))
    return SC.InstanceNiveau2({p.id: p for p in patients}, vacs, SC.ParametresHebergement(lits, places, 0))


def test_le_patient_sortant_n_est_pas_compte_la_nuit_suivant_son_depart():
    x = _hospitalise(1, nuits_apres=2)                                 # opéré lundi, sort mercredi à midi
    assert SC.periodes_occupation(x, LUNDI, HUIT_HEURES) == [LUNDI, MARDI]
    debut, fin = SC.intervalle_lit(x, LUNDI)
    assert fin.date() == MERCREDI and fin.time() == time(12)


def test_sortie_a_midi_et_admission_le_meme_jour_sur_le_meme_lit():
    x, y = _hospitalise(1, nuits_apres=2), _hospitalise(2, nuits_avant=1, nuits_apres=1)   # y : admis mercredi
    assert SC.intervalle_lit(x, LUNDI)[1] <= SC.intervalle_lit(y, JEUDI)[0]                   # successifs
    inst = _instance([x, y], lits=1)
    sol = SC.SolutionPatients({1: 0, 2: 3})                           # x opéré lundi, y jeudi (admis mercredi)
    assert VA.valider_niveau2(inst, sol).faisable
    assert SC.evaluer_niveau2(inst, sol).depassement_lits == 0


def test_deux_occupations_simultanees_sont_refusees():
    x, z = _hospitalise(1, nuits_apres=2), _hospitalise(2, nuits_apres=1)
    inst = _instance([x, z], lits=1)
    sol = SC.SolutionPatients({1: 0, 2: 1})                           # nuit de mardi : deux patients pour un lit
    assert "lits" in {v.type for v in VA.valider_niveau2(inst, sol).violations}
    assert SC.evaluer_niveau2(inst, sol).depassement_lits == 1


def test_une_place_sert_le_matin_puis_l_apres_midi_apres_remise_en_etat():
    matin = SC.periodes_occupation(_ambulatoire(1), LUNDI, HUIT_HEURES)[0]
    apres_midi = SC.periodes_occupation(_ambulatoire(2), LUNDI, QUATORZE_HEURES)[0]
    assert (matin.jour, matin.apres_midi, apres_midi.apres_midi) == (LUNDI, False, True)
    fin_matin, debut_apres_midi = SC.intervalle_place(matin)[1], SC.intervalle_place(apres_midi)[0]
    assert debut_apres_midi - fin_matin == timedelta(minutes=P_.DUREE_REMISE_EN_ETAT_PLACE_MIN)
    inst = _instance([_ambulatoire(1), _ambulatoire(2)], places=1)
    sol = SC.SolutionPatients({1: 0, 2: 5})                           # lundi matin puis lundi après-midi
    assert VA.valider_niveau2(inst, sol).faisable
    assert SC.evaluer_niveau2(inst, sol).depassement_places == 0
    assert SC.calculer_occupation_par_jour(inst, sol)[1] == {LUNDI: 1}


def test_deux_patients_ambulatoires_la_meme_demi_journee_sont_refuses():
    inst = _instance([_ambulatoire(1), _ambulatoire(2)], places=1)
    sol = SC.SolutionPatients({1: 0, 2: 0})                           # deux patients le lundi matin, une place
    violations = VA.valider_niveau2(inst, sol).violations
    assert [(v.type, v.objet) for v in violations] == [("places ambulatoires", f"{LUNDI.isoformat()} matin")]
    assert SC.evaluer_niveau2(inst, sol).depassement_places == 1


def test_meme_decompte_dans_le_niveau_2_le_sma_les_indicateurs(prog):
    lits_n2, places_n2 = SC.calculer_occupation(prog.instance2, prog.solution)
    ind = calculer_indicateurs_niveau2(prog.instance2, prog.solution)
    heb = S.simuler(prog, [], MATIN).modele.hebergement
    lits_sma, places_sma = heb.occupation()
    assert dict(lits_n2) == dict(lits_sma) == ind.occupation_lits_par_jour
    assert dict(places_n2) == dict(places_sma)                        # par demi-journée
    assert SC.par_jour(places_n2) == heb.occupation_par_jour()[1] == ind.occupation_places_par_jour
    assert VA.valider_niveau2(prog.instance2, prog.solution).faisable == (
        max(lits_n2.values()) <= prog.instance2.hebergement.cap_lits
        and max(places_n2.values()) <= prog.instance2.hebergement.cap_places)


def test_le_programme_respecte_les_lits_du_site():
    prog = P.calculer_programme(LUNDI, "glouton")
    lits, _ = SC.calculer_occupation_par_jour(prog.instance2, prog.solution)
    assert max(lits.values()) <= SC.HEBERGEMENT_SITE.cap_lits
