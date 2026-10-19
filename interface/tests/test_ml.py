# -*- coding: utf-8 -*-
"""Modèle de prédiction (machine_learning/) : données préparées, prédictions cohérentes, codes hors vocabulaire."""
from datetime import date

import pytest

from orchestre import chemins, ml


def _entrees(cim: str, type_intervention: str = "Osteosynthese Col Du Femur", age: int = 80):
    return ml.entrees_modele(type_intervention=type_intervention, cim_diag_pr=cim, ccam_1="", sexe="1",
                             praticien="CL", anesth_type="", anesth_loco_reg="", age_annees=age,
                             date_intervention=date(2026, 10, 19))


@pytest.fixture(scope="module")
def donnees():
    return ml.PREP.charger_et_preparer(chemins.CSV_HISTORIQUE)


def test_preparation_ecarte_les_sejours_sans_duree_de_bloc(donnees):
    assert len(donnees) > 14_000
    assert (donnees["duree_bloc_heures"] > 0).all()
    assert donnees[["duree_avant_operation", "duree_apres_operation"]].ge(0).all().all()


def test_les_modeles_attendent_les_colonnes_du_site():
    for modele in ml.modeles().values():
        assert list(modele.feature_names_in_) == ml.CAT_COLS + ml.NUM_COLS


def test_fracture_du_col_hospitalisee_et_urgente():
    p = ml.predire(_entrees("S72.00"))
    assert not p.ambulatoire and p.nuits_post_op >= 1 and p.score_urgence >= 8
    assert p.hors_vocabulaire == []


def test_code_hors_vocabulaire_signale():
    assert "cim_diag_pr" in ml.predire(_entrees("S72.0")).hors_vocabulaire


def test_arthroscopie_du_genou_ambulatoire_sans_nuit():
    p = ml.predire(_entrees("S83.2", type_intervention="Arthroscopie Genou", age=25))
    assert p.ambulatoire and (p.nuits_pre_op, p.nuits_post_op) == (0, 0)
    assert p.duree_bloc_min >= 15 and 1 <= p.priorite <= 4


def test_normalisation_et_controle_des_codes():
    assert ml.normaliser_cim("m161") == "M16.1"
    assert ml.verifier_codes("M17.1", "NFKA008") == []
    assert ml.verifier_codes("17.1", "NFK") != []


def test_metriques_affichees_sur_le_jeu_de_test(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "CACHE_METRIQUES", tmp_path / "metriques_ml.json")    # ne touche pas interface/donnees
    m = ml.metriques(recalculer=True)
    assert m["n_test"] < m["n_total"] and 0.85 < m["capacite"]["accuracy"] <= 1
    assert m["n_test_hospitalises"] == m["nuits_apres"]["n_test"] == m["nuits_avant"]["n_test"] < m["n_test"]
    assert {"mae", "rmse", "r2", "n_test"} <= set(m["duree_bloc_heures"]) and set(m["capacite"]["f1_par_classe"]) == {
        "ambulatoire", "lit_classique"}
    assert "urgence" not in m                                      # D8 : plus de R² pour une règle


def test_le_score_d_urgence_est_une_regle_et_non_un_modele():
    from preparation import regle_urgence
    assert regle_urgence("S72.00", "") == 9 and regle_urgence("M17.1", "NFKA008") == 1
    assert regle_urgence("L02.4", "") == 6 and regle_urgence("Z99.9", "INCONNU") == 3
    assert "reg_urgence" not in ml.modeles()
    p = ml.predire(_entrees("S72.00"))
    assert p.score_urgence == regle_urgence("S72.00", "") and p.priorite == ml.priorite_depuis_score(9)


def test_les_deux_scripts_et_l_interface_partagent_la_preparation(donnees):
    from preparation import separer
    tr, te = separer(donnees)
    assert abs(len(te) - 0.2 * len(donnees)) <= 1
    assert set(tr.index).isdisjoint(te.index)
