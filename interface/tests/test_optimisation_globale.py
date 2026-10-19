# -*- coding: utf-8 -*-
"""Optimisation globale demandée par l'administrateur : le RÉSULTAT est enregistré puis rejoué tel quel."""
from datetime import timedelta

from aide import LUNDI, MATIN, coherent, etat, reoptimisation
from orchestre import sma_service as S


def _deplacement_valide(sim):
    """Un patient de démonstration futur déplacé dans une vacation vide de son chirurgien (semaine 6)."""
    it = next(i for i in sim.modele.interventions() if not i.urgence and i.debut > MATIN + timedelta(days=3))
    fen = next(f for s in sim.modele.salles.values() for f in s.creneaux.values()
               if f.chirurgien_id == it.chirurgien_id and f.jour >= LUNDI + timedelta(weeks=6)
               and not s.du_creneau(f.id))
    return it, fen, {"methode": "memetique", "budget_s": 1, "score_avant": 0, "score_apres": 0,
                     "mouvements": [{"pid": it.pid, "salle_id": fen.salle_id, "fenetre_id": fen.id,
                                     "debut": fen.debut.isoformat(), "chirurgien_id": fen.chirurgien_id}]}


def test_un_programme_deja_bon_n_est_pas_modifie(prog):
    contenu, message, scores = S.calculer_reoptimisation(prog, [], MATIN, "TABOU seul", 1.0)
    assert contenu is None and "Aucun plan" in message
    assert scores["apres"] == scores["avant"]


def test_le_plan_enregistre_est_rejoue_a_l_identique(prog):
    sim = S.simuler(prog, [], MATIN)
    it, fen, contenu = _deplacement_valide(sim)
    evts = [reoptimisation(MATIN, contenu)]
    a, b = S.simuler(prog, evts, MATIN + timedelta(minutes=1)), S.simuler(prog, evts, MATIN + timedelta(minutes=1))
    nouveau = a.intervention(it.pid)
    assert (nouveau.salle_id, nouveau.fenetre_id, nouveau.debut) == (fen.salle_id, fen.id, fen.debut)
    assert etat(a) == etat(b) and coherent(a) == []
    assert any(d["type"] == "reoptimisation" for d in a.decisions())


def test_un_plan_devenu_invalide_est_refuse_avec_une_alerte(prog):
    sim = S.simuler(prog, [], MATIN)
    it, _, contenu = _deplacement_valide(sim)
    contenu["mouvements"][0]["fenetre_id"] = 999_999                        # créneau qui n'existe plus
    sim = S.simuler(prog, [reoptimisation(MATIN, contenu)], MATIN + timedelta(minutes=1))
    assert sim.intervention(it.pid).debut == it.debut
    assert any("non appliquée" in a for a in sim.alertes())
