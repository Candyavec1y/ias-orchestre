# -*- coding: utf-8 -*-
"""
commun/validation.py — VALIDATEUR DE FAISABILITÉ indépendant (D9)
==================================================================

Vérifie qu'une solution respecte les contraintes, en les recalculant UNE PAR UNE à partir de la solution et de
l'instance. Il n'utilise NI les fonctions objectif (evaluer_planning, evaluer_niveau2, EtatNiveau2), NI les fonctions
de pénalité, NI le code des algorithmes : une erreur dans le score ou dans une métaheuristique ne peut donc pas
masquer une violation. Seule la CONVENTION d'occupation des lits et places (periodes_occupation) est partagée : c'est
une définition métier, pas un calcul de score.

    valider_niveau1(instance1, solution1)  -> Validation
    valider_niveau2(instance2, solution2)  -> Validation
    Validation.faisable                    -> bool
    Validation.violations                  -> [Violation(type, objet, valeur, limite), ...]

Contraintes vérifiées
---------------------
  N1 : bloc affecté à une plage existante, plage LIBRE, salle autorisée pour le chirurgien, créneau dans ses
       disponibilités, au plus un bloc par salle et par créneau, un chirurgien dans une seule salle à la fois,
       besoins horaires couverts exactement.
  N2 : patient affecté, vacation existante, vacation du chirurgien du patient, date au plus tôt respectée,
       charge de chaque vacation dans sa capacité utile (durée moins la marge pour aléas), lits et places
       ambulatoires dans la capacité de chaque jour.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Union

from structures_communes import (InstanceNiveau2, InstanceProbleme, SolutionPatients, SolutionPlanning,
                                 periodes_occupation)

Valeur = Union[int, float, str]


@dataclass(frozen=True)
class Violation:
    type: str            # ex. "conflit de salle", "capacité de vacation", "lits"
    objet: str           # ce qui est concerné : bloc, patient, vacation, jour...
    valeur: Valeur       # valeur constatée
    limite: Valeur       # limite à respecter


@dataclass
class Validation:
    niveau: int
    violations: list[Violation] = field(default_factory=list)

    @property
    def faisable(self) -> bool:
        return not self.violations

    def par_type(self) -> dict[str, int]:
        return dict(Counter(v.type for v in self.violations))

    def resume(self) -> str:
        if self.faisable:
            return "solution faisable"
        return "NON VALIDE : " + ", ".join(f"{n} {t}" for t, n in sorted(self.par_type().items()))

    def to_dict(self) -> dict[str, Any]:
        return {"faisable": self.faisable, "par_type": self.par_type(),
                "violations": [asdict(v) for v in self.violations]}


def _chevauchent(a_debut: datetime, a_fin: datetime, b_debut: datetime, b_fin: datetime) -> bool:
    return a_debut < b_fin and b_debut < a_fin


# =============================================================================
# Niveau 1 : blocs des chirurgiens -> plages salle x créneau
# =============================================================================

def valider_niveau1(instance: InstanceProbleme, solution: SolutionPlanning) -> Validation:
    v = Validation(1)
    places: list[tuple[int, int, int]] = []          # (bloc, chirurgien, plage)
    for bloc_id, bloc in sorted(instance.blocs_a_placer.items()):
        plage_id = solution.affectations.get(bloc_id)
        if plage_id is None:
            v.violations.append(Violation("bloc non affecté", f"bloc {bloc_id}", "aucune plage", "une plage"))
            continue
        plage = instance.plages_bloc.get(plage_id)
        if plage is None:
            v.violations.append(Violation("plage inexistante", f"bloc {bloc_id}", plage_id, "plage de l'instance"))
            continue
        chir = instance.chirurgiens[bloc.chirurgien_id]
        if plage.type_plage != "LIBRE":
            v.violations.append(Violation("plage non disponible", f"bloc {bloc_id}", plage.type_plage, "LIBRE"))
        if plage.salle_id not in chir.salles_autorisees:
            v.violations.append(Violation("salle non autorisée", f"bloc {bloc_id} ({chir.nom})", plage.salle_id,
                                          f"salles {list(chir.salles_autorisees)}"))
        dispo = instance.disponibilites_chirurgiens.get(bloc.chirurgien_id)
        if dispo is not None and plage.creneau_id not in dispo:
            v.violations.append(Violation("chirurgien indisponible", f"bloc {bloc_id} ({chir.nom})",
                                          f"créneau {plage.creneau_id}", "créneaux disponibles"))
        places.append((bloc_id, bloc.chirurgien_id, plage_id))

    def intervalle(plage_id):
        c = instance.creneaux[instance.plages_bloc[plage_id].creneau_id]
        return datetime.combine(c.jour, c.heure_debut), datetime.combine(c.jour, c.heure_fin)

    for i, (b1, c1, p1) in enumerate(places):
        s1, (d1, f1) = instance.plages_bloc[p1].salle_id, intervalle(p1)
        for b2, c2, p2 in places[i + 1:]:
            s2, (d2, f2) = instance.plages_bloc[p2].salle_id, intervalle(p2)
            if not _chevauchent(d1, f1, d2, f2):
                continue
            if s1 == s2:
                v.violations.append(Violation("conflit de salle", f"salle {s1}, {d1:%d/%m %H:%M}",
                                              f"blocs {b1} et {b2}", "un bloc à la fois"))
            if c1 == c2 and s1 != s2:
                v.violations.append(Violation("conflit de chirurgien", f"{instance.chirurgiens[c1].nom}, "
                                              f"{d1:%d/%m %H:%M}", f"salles {s1} et {s2}", "une salle à la fois"))

    minutes: dict[int, float] = defaultdict(float)
    for _, cid, plage_id in places:
        d, f = intervalle(plage_id)
        minutes[cid] += (f - d).total_seconds() / 60
    for cid, chir in sorted(instance.chirurgiens.items()):
        besoin = chir.besoin_heures_semaine * 60
        if abs(minutes.get(cid, 0.0) - besoin) > 1e-6:
            v.violations.append(Violation("besoin horaire non couvert", chir.nom, minutes.get(cid, 0.0), besoin))
    return v


# =============================================================================
# Niveau 2 : patients -> vacations
# =============================================================================

def valider_niveau2(instance: InstanceNiveau2, solution: SolutionPatients) -> Validation:
    v = Validation(2)
    charge: dict[int, float] = defaultdict(float)
    lits: dict = defaultdict(int)
    places: dict = defaultdict(int)
    for pid, patient in sorted(instance.patients.items()):
        vid = solution.affectations.get(pid)
        if vid is None:
            v.violations.append(Violation("patient non affecté", f"patient {pid}", "aucune vacation", "une vacation"))
            continue
        vac = instance.vacations.get(vid)
        if vac is None:
            v.violations.append(Violation("vacation inexistante", f"patient {pid}", vid, "vacation de l'instance"))
            continue
        if vac.chirurgien_id != patient.chirurgien_id:
            v.violations.append(Violation("chirurgien incompatible", f"patient {pid}",
                                          f"vacation du chirurgien {vac.chirurgien_id}",
                                          f"chirurgien {patient.chirurgien_id}"))
        if patient.date_min is not None and vac.jour < patient.date_min:
            v.violations.append(Violation("date au plus tôt", f"patient {pid}", vac.jour.isoformat(),
                                          f">= {patient.date_min.isoformat()}"))
        charge[vid] += patient.duree_bloc
        compteur = places if patient.ambulatoire else lits
        for periode in periodes_occupation(patient, vac.jour, vac.heure_debut):
            compteur[periode] += 1

    for vid, minutes in sorted(charge.items()):
        vac = instance.vacations.get(vid)
        if vac is not None and minutes > vac.capacite_utile_minutes + 1e-9:
            v.violations.append(Violation("capacité de vacation", f"vacation {vid} ({vac.jour:%d/%m}, salle "
                                          f"{vac.salle_id})", minutes, vac.capacite_utile_minutes))
    h = instance.hebergement
    for jour, n in sorted(lits.items()):
        if n > h.cap_lits:
            v.violations.append(Violation("lits", jour.isoformat(), n, h.cap_lits))
    for periode, n in sorted(places.items()):                          # par demi-journée
        if n > h.cap_places:
            v.violations.append(Violation("places ambulatoires", str(periode), n, h.cap_places))
    return v
