# -*- coding: utf-8 -*-
"""Tâche A : environnement, provenance (commit, versions, empreintes) et contrôle rapide de préparation."""
from __future__ import annotations

import importlib.metadata as md
import os
import platform
import subprocess
import sys
import time

from commun_rapport import RACINE, SORTIE, commit_git, sha256

FICHIERS = ["commun/parametres.py", "commun/structures_communes.py", "commun/validation.py",
            "metaheuristiques/hybridation.py", "metaheuristiques/sorties.py",
            "planning_vacations/planning_vacations_v28.py", "sma/sma_urgences.py", "sma/optimisation_sma.py",
            "sma/metaheuristiques_sma.py", "sma/scenarios_sma.py", "machine_learning/preparation.py",
            "machine_learning/modele_prediction_rapide.py", "machine_learning/utilisation_modele.py",
            "machine_learning/donnees_hospitalieres.csv", "machine_learning/outputs/models_rapide/clf_type_capacite.joblib",
            "machine_learning/outputs/models_rapide/reg_duree_bloc.joblib",
            "machine_learning/outputs/models_rapide/reg_duree_avant.joblib",
            "machine_learning/outputs/models_rapide/reg_duree_apres.joblib", "interface/tests/saturation.py"]
PAQUETS = ["numpy", "pandas", "scikit-learn", "scipy", "mesa", "matplotlib", "streamlit", "joblib"]


def _cmd(args, **kw):
    t0 = time.perf_counter()
    r = subprocess.run(args, cwd=RACINE, capture_output=True, text=True, **kw)
    return r.returncode, time.perf_counter() - t0, (r.stdout + r.stderr)


def main():
    commit = commit_git()
    statut = subprocess.run(["git", "status", "--short"], cwd=RACINE, capture_output=True, text=True).stdout
    branche = subprocess.run(["git", "branch", "--show-current"], cwd=RACINE, capture_output=True, text=True).stdout
    mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout or 0)
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    perf = subprocess.run(["sysctl", "-n", "hw.perflevel0.physicalcpu"], capture_output=True, text=True).stdout.strip()
    eff = subprocess.run(["sysctl", "-n", "hw.perflevel1.physicalcpu"], capture_output=True, text=True).stdout.strip()
    lignes = ["# Environnement d'exécution", "",
              f"- Commit : `{commit}` (branche `{branche.strip()}`)",
              f"- État git au lancement : {'propre (hors resultats_rapport/)' if not [l_ for l_ in statut.splitlines() if 'resultats_rapport' not in l_] else 'MODIFIÉ'}",
              f"- Python : {sys.version.split()[0]} ({sys.executable})",
              f"- OS : {platform.platform()}",
              f"- CPU : {cpu}, {os.cpu_count()} cœurs logiques ({perf} performance + {eff} efficacité)",
              f"- RAM : {mem / 2**30:.0f} Gio",
              "- Mesure du temps : `time.perf_counter()` (temps réel écoulé, horloge monotone) ; les budgets des "
              "métaheuristiques sont des budgets de temps réel.", "", "## Bibliothèques", "",
              "| Paquet | Version |", "|---|---|"]
    lignes += [f"| {p} | {md.version(p)} |" for p in PAQUETS]
    lignes += ["", "## Empreintes SHA-256 des fichiers utilisés", "", "| Fichier | SHA-256 |", "|---|---|"]
    lignes += [f"| `{f}` | `{sha256(RACINE / f)}` |" for f in FICHIERS]
    (SORTIE / "environnement.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")

    # --- contrôle rapide de préparation : points d'entrée ---
    py = str(RACINE / ".venv" / "bin" / "python")
    controles = [("Scénarios SMA (liste)", [py, "sma/scenarios_sma.py", "--liste"]),
                 ("Scénario SMA insertion_simple", [py, "sma/scenarios_sma.py", "insertion_simple"]),
                 ("Aide de l'hybridation", [py, "metaheuristiques/hybridation.py", "--help"]),
                 ("Tests rapides (pytest -m 'not lent')", [py, "-m", "pytest", "interface/tests", "-m", "not lent",
                                                           "-q", "-p", "no:cacheprovider"])]
    res = []
    for nom, args in controles:
        code, duree, sortie = _cmd(args)
        derniere = [l_ for l_ in sortie.strip().splitlines() if l_.strip()][-1:] or [""]
        res.append((nom, code, duree, derniere[0][:120]))
    t = ["| Contrôle | Code retour | Durée (s) | Dernière ligne |", "|---|---|---|---|"]
    t += [f"| {n} | {c} | {d:.1f} | `{x}` |" for n, c, d, x in res]
    (SORTIE / "donnees_agregees" / "preparation_controles.md").write_text("\n".join(t) + "\n", encoding="utf-8")
    print("\n".join(t))


if __name__ == "__main__":
    main()
