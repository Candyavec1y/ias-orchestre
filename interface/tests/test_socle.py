# -*- coding: utf-8 -*-
"""Socle : une seule copie des structures communes, chiffrement, mots de passe, historique scellé."""
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from orchestre import chemins
from orchestre import stockage as DB


def test_une_seule_structure_commune_pour_tout_le_depot():
    import sma_urgences  # noqa: F401
    import sorties  # noqa: F401
    import structures_communes
    assert Path(structures_communes.__file__).parent == chemins.RACINE / "commun"
    assert hasattr(structures_communes, "type_semaine") and hasattr(structures_communes, "penalite_priorite_patient")


def test_reference_dossier_chiffree_et_mots_de_passe(base_isolee):
    f = DB.creer_patient(praticien="CT", entrees={}, prediction={}, valide={}, reference="IPP-123",
                         information_patient=True, auteur="test")
    brut = sqlite3.connect(DB.FICHIER_BASE).execute("SELECT ref_chiffree FROM patients").fetchone()[0]
    assert b"IPP-123" not in brut and DB.reference_dossier(f["id"]) == "IPP-123"
    DB.creer_utilisateur("u", "Mot-de-passe-2026!", "chirurgien", "U")
    assert DB.verifier_mot_de_passe("u", "Mot-de-passe-2026!") and not DB.verifier_mot_de_passe("u", "x")
    assert DB.mot_de_passe_robuste("court") and not DB.mot_de_passe_robuste("Mot-de-passe-2026!")
    DB.supprimer_patient(f["id"])
    assert DB.patient(f["id"]) is None


def test_historique_en_ajout_seul_et_scelle(base_isolee):
    DB.historiser("regulation", "regulation", "Urgence", "Déclaration d'urgence", patient="URG-001",
                  detail="vitale", motif="polytraumatisé", heure_metier=datetime(2026, 10, 13, 9, 0))
    DB.historiser("système (SMA)", "automatique", "Décision automatique", "Décalé +30 min", patient="DEMO-0001",
                  motif="Conséquence de : Déclaration d'urgence URG-001")
    assert DB.verifier_historique() == (True, 2, None)
    con = sqlite3.connect(DB.FICHIER_BASE)
    for sql in ("UPDATE historique SET motif='x' WHERE id=1", "DELETE FROM historique WHERE id=1"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    # falsification hors application (triggers supprimés) : la chaîne de sceaux la détecte
    con.execute("DROP TRIGGER historique_non_modifiable")
    con.execute("UPDATE historique SET motif='autre motif' WHERE id=1")
    con.commit()
    assert DB.verifier_historique() == (False, 2, 1)


def test_evenements_enregistres_et_rejoues_dans_l_ordre(base_isolee):
    DB.ajouter_evenement(datetime(2026, 10, 13, 10), "panne", {"ascenseur": "ML1"}, "test")
    DB.ajouter_evenement(datetime(2026, 10, 13, 9), "urgence", {"x": 1}, "test")
    assert [e["type"] for e in DB.lister_evenements()] == ["urgence", "panne"]
    empreinte = DB.empreinte_evenements()
    DB.supprimer_evenement(DB.lister_evenements()[0]["id"])
    assert DB.empreinte_evenements() != empreinte
