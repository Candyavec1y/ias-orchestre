# -*- coding: utf-8 -*-
"""
sma/metaheuristiques_sma.py — Pont entre les agents du SMA et VOS métaheuristiques
===================================================================================

Les agents n'ont pas de métaheuristique à eux : ils appellent le moteur du projet,
metaheuristiques/hybridation.py (AGS + RS + TABOU), SANS le modifier :

    "RS seul"        recuit_niveau2              (exploration)
    "TABOU seul"     tabou_niveau2               (intensification)
    "AGS seul"       AGSHybride sans recherche locale
    "memetique"      AGS dont les meilleurs enfants sont polis par le Tabou + intensification RS puis Tabou
    "AGS>RS>TABOU"   AGS pur puis RS puis Tabou sur le meilleur individu
    "RS>AGS>TABOU"   recherches locales de départ, AGS mémétique ensemencé, intensification finale

Ce moteur attend un problème de type ProblemeHybrideN2 : codage « une valeur par patient », état incrémental
(etat.deplacer / etat.score), mouvements (patient, ancienne valeur, nouvelle valeur). Les deux problèmes du SMA
(optimisation_sma.py) respectent exactement ce contrat :
    * ProblemeResiduel   (agent Optimisation) : valeur = créneau du programme  ;
    * ProblemeLocalSalle (agents Salle)       : valeur = rang de passage, ou « reporté ».

Budget : en secondes (convention de votre campagne de comparaison : même temps pour chaque mode) ou, pour
« RS seul » / « TABOU seul », en itérations (résultat reproductible, utile dans les agents Salle).
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

_RACINE = Path(__file__).resolve().parents[1]
for _d in (_RACINE / "planning_vacations", _RACINE / "metaheuristiques"):
    if _d.is_dir() and str(_d) not in sys.path:
        sys.path.append(str(_d))

import hybridation as H  # noqa: E402

from structures_communes import ParametresAGS
from sorties import SuiviExecution

MODES = ("RS seul", "TABOU seul", "AGS seul") + tuple(H.MODES)
NOMS = {"RS seul": "Recuit simulé", "TABOU seul": "Tabou", "AGS seul": "AGS", "memetique": "Mémétique (AGS+Tabou)",
        "AGS>RS>TABOU": "AGS > RS > Tabou", "RS>AGS>TABOU": "RS > AGS > Tabou", "glouton": "Glouton"}

# Réglages « temps réel » : mêmes algorithmes, voisinages et populations réduits (le SMA dispose de
# fractions de seconde à quelques secondes, contre 20 s dans la campagne hors ligne).
RL_GLOBAL = H.ParametresRechercheLocale(echanges_n2=120, ejections_n2=40, iterations_par_enfant=4, patience=15,
                                        force_perturbation=(3, 8))
AGS_GLOBAL = ParametresAGS(taille_population=16, generations=100_000, taux_croisement=0.9, taux_mutation=0.4,
                           taille_tournoi=3, elites=2)
RL_LOCAL = H.ParametresRechercheLocale(echanges_n2=40, ejections_n2=0, iterations_par_enfant=2, patience=8,
                                       force_perturbation=(1, 3))
AGS_LOCAL = ParametresAGS(taille_population=10, generations=100_000, taux_croisement=0.9, taux_mutation=0.4,
                          taille_tournoi=3, elites=2)


@dataclass
class ResultatOptimisation:
    mode: str
    individu: Any
    cout: float
    cout_initial: float
    evaluations: int
    temps_s: float
    suivi: Any = None

    @property
    def gain(self) -> float:
        return self.cout_initial - self.cout


def optimiser(pb, mode: str, temps_s: Optional[float] = None, iterations: Optional[int] = None, graine: int = 0,
              rl: Optional["H.ParametresRechercheLocale"] = None, ags: Optional[ParametresAGS] = None,
              depart=None, pas_suivi: int = 1) -> ResultatOptimisation:
    """Lance un mode du moteur hybride sur `pb` en démarrage à chaud (individu courant)."""
    if mode not in MODES:
        raise ValueError(f"mode inconnu : {mode!r} (attendu : {', '.join(MODES)})")
    suivi = SuiviExecution(pas_enregistrement=pas_suivi)
    pb.journal = H.Journal(suivi)
    if hasattr(pb, "_cache"):
        pb._cache.clear()
    pb.meilleur_faisable, pb.score_meilleur_faisable = None, float("inf")
    rl = rl or H.ParametresRechercheLocale()
    moteur_rl = H.RechercheLocaleMixte(2, pb, rl)
    depart = list(depart if depart is not None else pb.individu_courant())
    rng = random.Random(graine)
    with suivi:
        c0 = pb.cout(depart)
        if mode == "RS seul" and iterations:
            ind, c = moteur_rl.rs(depart, rng, iterations=iterations)
        elif mode == "TABOU seul" and iterations:
            ind, c = moteur_rl.tabou(depart, rng, iterations=iterations)
        else:
            p = H.ParametresHybride.pour_mode(mode, temps_s or 1.0, graine, rl=rl)
            if ags is not None:
                p = replace(p, ags=ags)
            ind, c, _ = H.resoudre(pb, moteur_rl, depart, p)
        ind = pb.solution_finale(ind)               # meilleure solution FAISABLE rencontrée (sinon la meilleure)
        c = pb.cout(ind)
    if c0 < c:                                        # le moteur garde son meilleur ; on ne régresse jamais
        ind, c = depart, c0
    return ResultatOptimisation(mode, ind, c, c0, suivi.nb_evaluations, suivi.temps_s, suivi)
