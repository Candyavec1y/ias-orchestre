# -*- coding: utf-8 -*-
"""
Planning des vacations (niveau 1) et programme opératoire (niveau 2).

* Planning des chirurgiens : planning de référence planning_vacations_v28 (parité des semaines),
  ou planning recalculé par l'hybridation AGS+RS+TABOU (hybridation.py) sur l'instance d'étude du niveau 1.
* Programme opératoire (patients -> vacations) : hybridation.py (mode hybride ou référence RS / Tabou / AGS
  seul), sur les vacations v28 de l'horizon. Ce programme sert d'état initial au système multi-agent.
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import chemins

import structures_communes as SC  # noqa: E402
import planning_vacations_v28 as V28  # noqa: E402
import sma_urgences as SMA  # noqa: E402
from validation import valider_niveau2  # noqa: E402
from parametres import (  # noqa: E402,F401  (ré-exportés pour l'interface : P.NB_SEMAINES_HORIZON...)
    BUDGET_OPTIMISATION_S, CHARGES_PAR_SEMAINE, NB_SEMAINES_HORIZON, NB_SEMAINES_SMA,
)

# Le planning des vacations (v28, cycle fixe de 4 semaines) est supposé IDENTIQUE sur toutes les semaines à venir :
# le SMA connaît ses vacations sur NB_SEMAINES_SMA semaines (au-delà des NB_SEMAINES_HORIZON semaines optimisées,
# semaines ouvertes sans patient de démonstration). Une inscription ou un report trouve donc toujours un créneau.
# Hébergement : SC.HEBERGEMENT_SITE (commun/parametres.py), modifiable par l'administrateur.


# Méthodes retenues (campagne v3, resultats_rapport/RESUME.md) : RS seul pour le programme opératoire (meilleur objectif
# F2 + report à tous les budgets) ; AGS>RS>TABOU comme hybridation de référence ; N1 : RS seul ou RS>AGS>TABOU.
MODE_PROGRAMME = "RS seul"
MODES_PLANNING_N1 = ("RS seul", "RS>AGS>TABOU")

MODES_HYBRIDES = {
    "RS seul": "Recuit simulé seul (méthode retenue)",
    "AGS>RS>TABOU": "Séquentiel AGS → RS → Tabou (hybridation de référence)",
    "RS>AGS>TABOU": "Séquentiel RS → AGS → Tabou",
    "memetique": "Mémétique (AGS + polissage Tabou, finale RS→Tabou)",
    "TABOU seul": "Recherche taboue seule",
    "AGS seul": "Algorithme génétique seul",
    "glouton": "Glouton multi-départ (sans métaheuristique)",
}


def lundi_de(jour: date) -> date:
    return jour - timedelta(days=jour.weekday())


# =============================================================================
# PLANNING DES VACATIONS (CHIRURGIENS)
# =============================================================================

@dataclass
class CaseVacation:
    jour: date
    salle_id: int
    salle: str
    debut: str
    fin: str
    code: str                 # code praticien, "URGENCE" ou "LIBRE"
    type: str                 # "vacation" | "urgence" | "libre"
    minutes: int
    vacation_id: int


def planning_semaine_v28(jour: date) -> tuple[str, list[CaseVacation]]:
    """Vacations v28 de la semaine contenant `jour` (type de semaine déduit de la date)."""
    lundi = lundi_de(jour)
    _, vacations, _ = V28.construire_semaine(lundi)
    cases = []
    for v in sorted(vacations.values(), key=lambda v: (v.jour, v.salle_id, v.heure_debut)):
        code = V28.NOM_PAR_ID[v.chirurgien_id]
        t = "urgence" if v.chirurgien_id == V28.ID_URGENCE else "libre" if v.chirurgien_id == V28.ID_LIBRE else "vacation"
        cases.append(CaseVacation(v.jour, v.salle_id, V28.SALLES[v.salle_id].nom, f"{v.heure_debut:%H:%M}",
                                  f"{v.heure_fin:%H:%M}", code, t, v.duree_minutes, v.id))
    return SC.type_semaine(lundi), cases


def praticiens_v28() -> list[str]:
    return sorted(n for n in V28.ID_PAR_NOM if n not in (V28.NOM_URGENCE, V28.NOM_LIBRE))


def heures_par_praticien(cases: list[CaseVacation]) -> dict[str, float]:
    h: dict[str, float] = {}
    for c in cases:
        if c.type == "vacation":
            h[c.code] = h.get(c.code, 0) + c.minutes / 60
    return dict(sorted(h.items()))


@dataclass
class ResultatNiveau1:
    """Planning des vacations recalculé par les métaheuristiques (instance d'étude)."""
    resultats: list                       # ResultatMetaheuristique (un par mode)
    meilleur: object
    instance: object
    cases: list[CaseVacation] = field(default_factory=list)
    journal: str = ""


def recalculer_planning_niveau1(modes: Optional[list[str]] = None, temps_s: float = BUDGET_OPTIMISATION_S,
                                graine: int = SC.GRAINE_ETUDE) -> ResultatNiveau1:
    """Niveau 1 de hybridation.py (AGS+RS+TABOU) sur l'instance d'étude commune (8 chirurgiens,
    3 salles, créneaux de 2 h). Le planning v28 réel n'est pas découpé en créneaux de 2 h : il ne peut
    pas être ré-optimisé tel quel au niveau 1 (voir CHOIX.md)."""
    H = chemins.module("hybridation")
    modes = list(modes or MODES_PLANNING_N1)
    inst1 = SC.construire_instance_etude()
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        res = H._executer_niveau(1, inst1, modes, temps_s, graine, H.ParametresRechercheLocale())
    faisables = [r for r in res if r.faisable] or res
    best = min(faisables, key=lambda r: r.score_final)
    cases = []
    for v in sorted(best.vacations.values(), key=lambda v: (v.jour, v.salle_id, v.heure_debut)):
        cases.append(CaseVacation(v.jour, v.salle_id, inst1.salles[v.salle_id].nom, f"{v.heure_debut:%H:%M}",
                                  f"{v.heure_fin:%H:%M}", inst1.chirurgiens[v.chirurgien_id].nom, "vacation",
                                  v.duree_minutes, v.id))
    # plages réservées aux urgences de l'instance d'étude
    for p in inst1.plages_bloc.values():
        if p.type_plage == "URGENCE":
            c = inst1.creneaux[p.creneau_id]
            cases.append(CaseVacation(c.jour, p.salle_id, inst1.salles[p.salle_id].nom, f"{c.heure_debut:%H:%M}",
                                      f"{c.heure_fin:%H:%M}", "URGENCE", "urgence", c.duree_minutes, -p.id))
    return ResultatNiveau1(res, best, inst1, cases, tampon.getvalue())


# =============================================================================
# PROGRAMME OPÉRATOIRE (PATIENTS -> VACATIONS)
# =============================================================================

def construire_instances(lundi: date, nb_semaines: int = NB_SEMAINES_HORIZON, graine: int = SC.GRAINE_PATIENTS,
                         charges=CHARGES_PAR_SEMAINE, hebergement=SC.HEBERGEMENT_SITE):
    """Instances N1/N2 sur `nb_semaines` à partir de `lundi` (planning v28) avec une programmation existante FICTIVE
    (patients DEMO-xxxx de generer_patients_etude), décroissante dans le temps (CHARGES_PAR_SEMAINE)."""
    return SMA.construire_instances_v28(lundi_de(lundi), nb_semaines, graine=graine, hebergement=hebergement,
                                        charges=charges, format_nom="DEMO-{:04d}")


def instances_sma(programme: "Programme", nb_semaines: int = NB_SEMAINES_SMA):
    """Instances du SMA : mêmes patients et mêmes identifiants de vacations que le programme optimisé (4 semaines),
    plus les vacations des semaines suivantes du planning fixe."""
    cle = ("_instances_sma", nb_semaines, V28.REVISION)
    if getattr(programme, "_cache_sma", (None,))[0] != cle:
        i1, i2 = SMA.construire_instances_v28(programme.lundi, max(nb_semaines, programme.nb_semaines),
                                              patients=programme.instance2.patients,
                                              hebergement=programme.instance2.hebergement)
        programme._cache_sma = (cle, i1, i2)
    return programme._cache_sma[1], programme._cache_sma[2]


@dataclass
class Programme:
    lundi: date
    nb_semaines: int
    mode: str
    temps_s: float
    graine: int
    instance1: object
    instance2: object
    solution: object                       # SolutionPatients
    resultat: Optional[object] = None      # ResultatMetaheuristique (None pour le glouton)
    score_glouton: float = 0.0
    calcule_le: str = ""
    validation: dict = field(default_factory=dict)   # validateur indépendant (commun/validation.py)


def calculer_programme(lundi: date, mode: str = MODE_PROGRAMME, temps_s: float = BUDGET_OPTIMISATION_S,
                       nb_semaines: int = NB_SEMAINES_HORIZON, graine: int = SC.GRAINE_ETUDE,
                       hebergement=SC.HEBERGEMENT_SITE) -> Programme:
    i1, i2 = construire_instances(lundi, nb_semaines, hebergement=hebergement)
    glouton = SC.construire_meilleure_affectation_initiale(i2)
    s_glouton = SC.evaluer_niveau2(i2, glouton).score_total
    resultat = None
    if mode == "glouton":
        sol = glouton
    else:
        H = chemins.module("hybridation")
        with contextlib.redirect_stdout(io.StringIO()):
            resultat = H._executer_niveau(2, i2, [mode], temps_s, graine, H.ParametresRechercheLocale())[0]
        sol = resultat.solution_patients()
    return Programme(lundi_de(lundi), nb_semaines, mode, temps_s, graine, i1, i2, sol, resultat, s_glouton,
                     datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None).isoformat(timespec="seconds"),
                     validation=valider_niveau2(i2, sol).to_dict())


def indicateurs(programme: Programme):
    sorties = chemins.module("sorties")
    return sorties.calculer_indicateurs_niveau2(programme.instance2, programme.solution)
