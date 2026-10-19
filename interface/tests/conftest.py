# -*- coding: utf-8 -*-
"""
Fixtures communes.

* `prog`            programme de test (glouton commun, 4 semaines à partir du 12/10/2026) : rapide et déterministe ;
* `base_isolee`     base SQLite et clés dans un dossier temporaire : AUCUN test ne touche interface/donnees/ ;
* `planning_neutre` (automatique) remet le planning des vacations d'origine après chaque test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aide import LUNDI  # noqa: E402
from orchestre import programme as P  # noqa: E402
from orchestre import stockage as DB  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "lent: test de plusieurs dizaines de secondes (exclure avec -m 'not lent')")


@pytest.fixture(scope="session")
def prog() -> P.Programme:
    return P.calculer_programme(LUNDI, "glouton")


@pytest.fixture
def base_isolee(tmp_path, monkeypatch):
    for nom, fichier in (("FICHIER_BASE", "orchestre.db"), ("FICHIER_CLE", "chiffrement.key"),
                         ("FICHIER_CLE_HISTORIQUE", "historique.key")):
        monkeypatch.setattr(DB, nom, tmp_path / fichier)
    DB.initialiser()
    return tmp_path


@pytest.fixture(autouse=True)
def planning_neutre():
    """Les versions du planning des vacations vivent dans le module : on les remet à zéro après chaque test."""
    V = P.V28
    ids, noms = dict(V.ID_PAR_NOM), dict(V.NOM_PAR_ID)
    yield
    V.definir_versions([])
    V.ID_PAR_NOM.clear(); V.ID_PAR_NOM.update(ids)
    V.NOM_PAR_ID.clear(); V.NOM_PAR_ID.update(noms)
    if hasattr(V, "_empreinte_site"):
        del V._empreinte_site
