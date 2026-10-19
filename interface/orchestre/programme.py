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
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import chemins

import structures_communes as SC  # noqa: E402
import planning_vacations_v28 as V28  # noqa: E402
import sma_urgences as SMA  # noqa: E402

# Charge de la programmation déjà existante, semaine par semaine (un programme se remplit à
# l'approche de la date). Bornes (min, max) en fraction des heures de vacation du chirurgien.
CHARGES_PAR_SEMAINE = ((0.85, 1.00), (0.60, 0.75), (0.35, 0.50), (0.10, 0.25))
NB_SEMAINES_HORIZON = 4
# Le planning des vacations (v28, cycle fixe de 4 semaines) est supposé IDENTIQUE sur toutes les semaines à venir :
# le SMA connaît ses vacations sur NB_SEMAINES_SMA semaines (au-delà des 4 semaines optimisées, semaines ouvertes
# sans patient de démonstration). Une inscription ou un report trouve donc toujours un créneau, plus tard au besoin.
NB_SEMAINES_SMA = 52
# Hébergement : les valeurs de l'étude (14 lits / 10 places) ont été calibrées pour 8 chirurgiens ;
# le planning v28 en compte une vingtaine sur 4 salles -> capacités relevées (voir CHOIX.md).
HEBERGEMENT_V28 = SC.ParametresHebergement(lits_disponibles_par_jour=30, places_ambulatoires_par_jour=20,
                                           reserve_lits=3)

MODES_HYBRIDES = {
    "memetique": "Mémétique (AGS + polissage Tabou, finale RS→Tabou)",
    "AGS>RS>TABOU": "Séquentiel AGS → RS → Tabou",
    "RS>AGS>TABOU": "Séquentiel RS → AGS → Tabou",
    "RS seul": "Recuit simulé seul (référence)",
    "TABOU seul": "Recherche taboue seule (référence)",
    "AGS seul": "Algorithme génétique seul (référence)",
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


def recalculer_planning_niveau1(modes: list[str], temps_s: float, graine: int = SC.GRAINE_ETUDE
                                ) -> ResultatNiveau1:
    """Niveau 1 de hybridation.py (AGS+RS+TABOU) sur l'instance d'étude commune (8 chirurgiens,
    3 salles, créneaux de 2 h). Le planning v28 réel n'est pas découpé en créneaux de 2 h : il ne peut
    pas être ré-optimisé tel quel au niveau 1 (voir CHOIX.md)."""
    H = chemins.module("hybridation")
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
                         charges=CHARGES_PAR_SEMAINE, hebergement=HEBERGEMENT_V28):
    """Instances N1/N2 du SMA sur `nb_semaines` à partir de `lundi` (planning v28) avec une
    programmation existante FICTIVE (générateur commun de l'étude), décroissante dans le temps."""
    lundi = lundi_de(lundi)
    spe = SMA.specialites_par_id()
    patients, pid = {}, 1
    for k in range(nb_semaines):
        lundi_k = lundi + timedelta(weeks=k)
        _, vac_k, _ = V28.construire_semaine(lundi_k)
        dec = k * SMA.DECALAGE_ID_SEMAINE
        reelles = {vid + dec: replace(v, id=vid + dec) for vid, v in vac_k.items()
                   if v.chirurgien_id not in (V28.ID_URGENCE, V28.ID_LIBRE)}
        cmin, cmax = charges[min(k, len(charges) - 1)]
        for p in SC.generer_patients_etude(reelles, graine + 97 * k, cmin, cmax).values():
            patients[pid] = replace(p, id=pid, date_min=lundi_k, nom=f"DEMO-{pid:04d}",
                                    specialite=spe.get(p.chirurgien_id, ""))
            pid += 1
    return SMA.construire_instances_v28(lundi, nb_semaines, patients=patients, hebergement=hebergement)


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


def calculer_programme(lundi: date, mode: str = "memetique", temps_s: float = 15.0,
                       nb_semaines: int = NB_SEMAINES_HORIZON, graine: int = SC.GRAINE_ETUDE,
                       hebergement=HEBERGEMENT_V28) -> Programme:
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
                     datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None).isoformat(timespec="seconds"))


def indicateurs(programme: Programme):
    sorties = chemins.module("sorties")
    return sorties.calculer_indicateurs_niveau2(programme.instance2, programme.solution)
