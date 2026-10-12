# -*- coding: utf-8 -*-
"""
Accès au code du dépôt depuis l'interface.

Le dépôt n'est pas un paquet Python : chaque dossier (machine_learning/, metaheuristiques/,
planning_vacations/, sma/) importe ses voisins par leur nom. On place donc ces dossiers dans
sys.path, avec commun/ EN PREMIER pour que tous partagent la version fusionnée de
structures_communes.py (voir commun/structures_communes.py).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_INTERFACE = RACINE / "interface"
DOSSIER_DONNEES = DOSSIER_INTERFACE / "donnees"          # base locale, clés, caches (ignoré par git)
DOSSIER_MODELES_ML = RACINE / "machine_learning" / "outputs" / "models_rapide"
CSV_HISTORIQUE = RACINE / "machine_learning" / "donnees_hospitalieres.csv"

_DOSSIERS = ["commun", "planning_vacations", "metaheuristiques", "sma", "machine_learning"]

for _nom in reversed(_DOSSIERS):
    _d = str(RACINE / _nom)
    if _d in sys.path:
        sys.path.remove(_d)
    sys.path.insert(0, _d)

# Import immédiat : les modules qui font ensuite sys.path.insert(0, leur_dossier) réutiliseront
# ce module déjà chargé (sys.modules) au lieu de leur copie locale.
import structures_communes  # noqa: E402,F401

DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)


def importer_fichier(nom_module: str, chemin: Path):
    """Importe un fichier dont le nom n'est pas un identifiant Python (ex. recuit_simulé.py)."""
    if nom_module in sys.modules:
        return sys.modules[nom_module]
    spec = importlib.util.spec_from_file_location(nom_module, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom_module] = module
    spec.loader.exec_module(module)
    return module


def module(nom: str):
    return importlib.import_module(nom)
