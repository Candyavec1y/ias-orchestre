# -*- coding: utf-8 -*-
"""
Reports sur plusieurs semaines (vérification R1 du nettoyage) : l'extension d'horizon de l'hybridation ne duplique
aucune vacation sur un créneau existant, ne compte pas deux fois les vacations régulières, respecte le planning
réel v28 (disponibilités des chirurgiens) et la pénalité de report correspond au décalage appliqué.
"""
from collections import Counter
from datetime import timedelta

import pytest

from aide import LUNDI
from orchestre import chemins
from orchestre import programme as P

import structures_communes as SC

H = chemins.module("hybridation")
V28 = P.V28


def _cle(v):
    return v.salle_id, v.jour, v.heure_debut


@pytest.fixture(scope="module", params=["etude", "v28_4_semaines"])
def etendue(request):
    base = SC.instance_niveau2_reference()[1] if request.param == "etude" else H.instance_v28(LUNDI, 4)
    return base, H.etendre_horizon(base, H.NB_SEMAINES_REPORT)


def test_aucune_vacation_dupliquee_sur_un_meme_creneau(etendue):
    _, ext = etendue
    doublons = [k for k, n in Counter(_cle(v) for v in ext.vacations.values()).items() if n > 1]
    assert doublons == []


def test_les_vacations_regulieres_ne_sont_pas_comptees_deux_fois(etendue):
    base, ext = etendue
    regulieres = {vid for vid, v in ext.vacations.items() if not v.supplementaire}
    assert regulieres == set(base.vacations)
    fin = max(v.jour for v in base.vacations.values())
    assert all(v.jour > fin for v in ext.vacations.values() if v.supplementaire)
    nb_semaines = {v.semaine_decalage for v in ext.vacations.values() if v.supplementaire}
    assert nb_semaines == set(range(1, H.NB_SEMAINES_REPORT + 1))


def test_les_reports_v28_suivent_le_planning_reel():
    """Chaque vacation de report existe dans le planning v28 de sa semaine : le chirurgien y est disponible."""
    ext = H.etendre_horizon(H.instance_v28(LUNDI, 4), H.NB_SEMAINES_REPORT)
    for v in ext.vacations.values():
        if not v.supplementaire:
            continue
        lundi = v.jour - timedelta(days=v.jour.weekday())
        _, reelles, _ = V28.construire_semaine(lundi)
        assert any((r.jour, r.salle_id, r.heure_debut, r.heure_fin, r.chirurgien_id) ==
                   (v.jour, v.salle_id, v.heure_debut, v.heure_fin, v.chirurgien_id) for r in reelles.values())


def test_la_penalite_de_report_correspond_au_decalage_applique():
    base = SC.instance_niveau2_reference()[1]                              # horizon d'une semaine
    ext = H.etendre_horizon(base, H.NB_SEMAINES_REPORT)
    pid, p = next(iter(base.patients.items()))
    origine = next(v for v in base.vacations.values() if v.chirurgien_id == p.chirurgien_id)
    for k in range(1, H.NB_SEMAINES_REPORT + 1):
        supp = next(v for v in ext.vacations.values() if v.supplementaire and v.semaine_decalage == k
                    and (v.salle_id, v.heure_debut, v.chirurgien_id, v.jour.weekday()) ==
                    (origine.salle_id, origine.heure_debut, origine.chirurgien_id, origine.jour.weekday()))
        assert (supp.jour - origine.jour).days == 7 * k
        etat = H.EtatAvecReport(ext, {pid: supp.id})
        assert etat.report == pytest.approx(H.PENALITE_SEMAINE_REPORT * H.POIDS_PRIORITE_REPORT[p.priorite] * k)
