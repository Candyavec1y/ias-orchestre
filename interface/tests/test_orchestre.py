# -*- coding: utf-8 -*-
"""Tests du noyau de l'interface (sans navigateur) :  python -m pytest interface/tests -q"""
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestre import chemins, ml, programme as P, sma_service as S, stockage as DB  # noqa: E402

LUNDI = date(2026, 10, 12)


@pytest.fixture(scope="module")
def prog():
    return P.calculer_programme(LUNDI, "glouton")


def test_une_seule_structure_commune():
    import structures_communes, sorties, sma_urgences  # noqa: F401
    assert Path(structures_communes.__file__).parent == chemins.RACINE / "commun"
    assert hasattr(structures_communes, "type_semaine") and hasattr(structures_communes, "penalite_priorite_patient")


def test_prediction_ml():
    e = ml.entrees_modele(type_intervention="Prothese Totale Hanche", cim_diag_pr="M161", ccam_1="NEKA020",
                          sexe="1", praticien="CL", anesth_type="AG avec intubation", anesth_loco_reg="Inconnu",
                          age_annees=78, date_intervention=date(2026, 10, 20))
    p = ml.predire(e)
    assert e["cim_diag_pr"] == "M16.1"
    assert not p.ambulatoire and p.duree_bloc_min > 30 and 1 <= p.priorite <= 4


def test_codes():
    assert ml.verifier_codes("M17.1", "NFKA008") == []
    assert ml.verifier_codes("17.1", "NFK") != []


def test_planning_v28_parite():
    t, cases = P.planning_semaine_v28(LUNDI)
    assert t == "paire" and any(c.type == "urgence" for c in cases)


def test_programme_et_rejeu_coherent(prog):
    fiche = {"id": 1, "pseudo": "PAT-T-0001", "praticien": "CT",
             "entrees": {"age_annees": 60, "sexe": "1", "type_intervention": "PTH", "cim_diag_pr": "M16.1"}}
    valide = {"duree_bloc_min": 90, "ambulatoire": False, "nuits_pre_op": 0, "nuits_post_op": 3, "priorite": 2,
              "date_min": "2026-10-14"}
    p = S.patient_consultation(fiche, valide)
    sim = S.simuler(prog, [], datetime(2026, 10, 13, 9, 0))
    n_msg = len(sim.modele.journal)
    props = S.proposer_creneaux(sim, p, date(2026, 10, 14))
    assert props and len(sim.modele.journal) == n_msg            # proposer ne modifie pas l'état
    evts = [
        {"id": 1, "heure": datetime(2026, 10, 13, 9, 0), "type": "inscription", "patient_id": 1,
         "contenu": {"patient": S.patient_vers_dict(p), "jour_min": "2026-10-14",
                     "salle_id": props[0]["salle_id"], "fenetre_id": props[0]["fenetre_id"]}},
        {"id": 2, "heure": datetime(2026, 10, 13, 9, 40), "type": "urgence", "patient_id": None,
         "contenu": {"patient": S.patient_vers_dict(S.patient_urgent(1, "CT", 60, ambulatoire=False, nuits_post_op=1)),
                     "gravite": "urgente"}},
        {"id": 3, "heure": datetime(2026, 10, 13, 10, 15), "type": "panne", "patient_id": None,
         "contenu": {"ascenseur": "ML1", "fin_estimee": "2026-10-13T13:00:00"}},
    ]
    sim = S.simuler(prog, evts, datetime(2026, 10, 13, 18, 0))
    assert sim.modele.verifier_coherence() == []
    it = sim.intervention(S.pid_consultation(1))
    assert it is not None and it.debut_initial.time().hour >= 7          # heure initiale = 1er placement
    assert sim.modele.bilan()["urgences_inserees"] == 1
    # annulation : le créneau est libéré
    evts.append({"id": 4, "heure": datetime(2026, 10, 13, 18, 30), "type": "annulation", "patient_id": 1,
                 "contenu": {"pid": S.pid_consultation(1)}})
    sim = S.simuler(prog, evts, datetime(2026, 10, 13, 19, 0))
    assert sim.intervention(S.pid_consultation(1)) is None and sim.modele.verifier_coherence() == []


def test_stockage_chiffrement_et_mdp(tmp_path, monkeypatch):
    monkeypatch.setattr(DB, "FICHIER_BASE", tmp_path / "t.db")
    monkeypatch.setattr(DB, "FICHIER_CLE", tmp_path / "t.key")
    DB.initialiser()
    f = DB.creer_patient(praticien="CT", entrees={}, prediction={}, valide={}, reference="IPP-123",
                         information_patient=True, auteur="test")
    import sqlite3
    brut = sqlite3.connect(tmp_path / "t.db").execute("SELECT ref_chiffree FROM patients").fetchone()[0]
    assert b"IPP-123" not in brut and DB.reference_dossier(f["id"]) == "IPP-123"
    DB.creer_utilisateur("u", "Mot-de-passe-2026!", "chirurgien", "U")
    assert DB.verifier_mot_de_passe("u", "Mot-de-passe-2026!") and not DB.verifier_mot_de_passe("u", "x")
    assert DB.mot_de_passe_robuste("court") and not DB.mot_de_passe_robuste("Mot-de-passe-2026!")
    DB.supprimer_patient(f["id"])
    assert DB.patient(f["id"]) is None


def test_historique_ajout_seul_et_scelle(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(DB, "FICHIER_BASE", tmp_path / "t.db")
    monkeypatch.setattr(DB, "FICHIER_CLE_HISTORIQUE", tmp_path / "h.key")
    DB.initialiser()
    DB.historiser("regulation", "regulation", "Urgence", "Déclaration d'urgence", patient="URG-001",
                  detail="vitale", motif="polytraumatisé", heure_metier=datetime(2026, 10, 13, 9, 0))
    DB.historiser("système (SMA)", "automatique", "Décision automatique", "Décalé +30 min", patient="DEMO-0001",
                  motif="Conséquence de : Déclaration d'urgence URG-001")
    assert DB.verifier_historique() == (True, 2, None)
    con = sqlite3.connect(tmp_path / "t.db")
    for sql in ("UPDATE historique SET motif='x' WHERE id=1", "DELETE FROM historique WHERE id=1"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    # falsification hors application (triggers supprimés) : la chaîne de sceaux la détecte
    con.execute("DROP TRIGGER historique_non_modifiable")
    con.execute("UPDATE historique SET motif='autre motif' WHERE id=1")
    con.commit()
    assert DB.verifier_historique() == (False, 2, 1)
