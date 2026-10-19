# -*- coding: utf-8 -*-
"""
Convention d'occupation des lits (Q13) : sortie à midi, lit réutilisable le jour même après remise en état, jamais
deux patients à la fois dans un lit ; même décompte dans le niveau 2, le SMA, les indicateurs et le validateur.
"""
from datetime import time, timedelta

from aide import LUNDI, MATIN
from orchestre import programme as P
from orchestre import sma_service as S

import structures_communes as SC
import validation as VA
from sorties import calculer_indicateurs_niveau2

MARDI, MERCREDI, JEUDI = (LUNDI + timedelta(days=k) for k in (1, 2, 3))


def _hospitalise(pid, nuits_avant=0, nuits_apres=2, chirurgien=1):
    return SC.Patient(pid, chirurgien, 60, ambulatoire=False, nuits_pre_op=nuits_avant, nuits_post_op=nuits_apres)


def _instance(patients, lits=1):
    vacs = {k: SC.Vacation(k, 1, 1, LUNDI + timedelta(days=k), time(8), time(13)) for k in range(5)}
    return SC.InstanceNiveau2({p.id: p for p in patients}, vacs, SC.ParametresHebergement(lits, 5, 0))


def test_le_patient_sortant_n_est_pas_compte_la_nuit_suivant_son_depart():
    x = _hospitalise(1, nuits_apres=2)                                 # opéré lundi, sort mercredi à midi
    assert SC.jours_occupation(x, LUNDI) == [LUNDI, MARDI]
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


def test_meme_decompte_dans_le_niveau_2_le_sma_les_indicateurs(prog):
    lits_n2, places_n2 = SC.calculer_occupation_par_jour(prog.instance2, prog.solution)
    ind = calculer_indicateurs_niveau2(prog.instance2, prog.solution)
    lits_sma, places_sma = S.simuler(prog, [], MATIN).modele.hebergement.occupation()
    assert dict(lits_n2) == dict(lits_sma) == ind.occupation_lits_par_jour
    assert dict(places_n2) == dict(places_sma) == ind.occupation_places_par_jour
    assert VA.valider_niveau2(prog.instance2, prog.solution).faisable == (
        max(lits_n2.values()) <= prog.instance2.hebergement.cap_lits
        and max(places_n2.values()) <= prog.instance2.hebergement.cap_places)


def test_le_programme_respecte_les_lits_du_site():
    prog = P.calculer_programme(LUNDI, "glouton")
    lits, _ = SC.calculer_occupation_par_jour(prog.instance2, prog.solution)
    assert max(lits.values()) <= SC.HEBERGEMENT_SITE.cap_lits
