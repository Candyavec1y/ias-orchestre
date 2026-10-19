# -*- coding: utf-8 -*-
# ==============================================================================================
# commun/structures_communes.py — VERSION FUSIONNÉE utilisée par l'interface OR'CHESTRE
# Le dépôt contenait deux copies divergentes de ce fichier :
#   planning_vacations/ (parité des semaines : type_semaine, planning_pour_semaine, Vacation.semaines)
#   metaheuristiques/   (priorité : penalite_priorite_patient)
# Ce fichier est leur UNION, sans aucune modification de code ; les deux copies ont été supprimées.
# Tous les scripts (interface, métaheuristiques, planning v28, SMA) l'importent depuis commun/ et
# partagent donc les MÊMES classes.
# ==============================================================================================
"""
structures_communes.py  (v2)
============================

Structures de données et fonctions PARTAGÉES par tout le dépôt : les métaheuristiques
(hybridation AGS + RS + Tabou, metaheuristiques/hybridation.py), le planning v28, le système
multi-agent et l'interface.

Organisation
------------
    0. CONSTANTES
    1. COMMUN
       1.1 Données métier      Chirurgien, Salle, Creneau, PlageBloc, BlocAPlacer, Vacation, Patient
       1.2 Instances           InstanceProbleme (N1), ParametresHebergement, InstanceNiveau2 (N2)
       1.3 Solutions           SolutionPlanning (N1), SolutionPatients (N2)
       1.4 Fonctions objectif  ParametresNiveau1, PoidsNiveau2
       1.5 Évaluations         EvaluationPlanning, EvaluationNiveau2
       1.6 Outils niveau 1     domaines, évaluation, vérification, solution initiale, vacations,
                               parité des semaines (type_semaine, planning_pour_semaine)
       1.7 Outils niveau 2     occupation, évaluation complète, évaluation INCRÉMENTALE, glouton
       1.8 Interface commune   ProblemeOptimisation
       1.9 Données de l'étude  instance N1, générateur de patients, instance N2 de référence
    2. AGS    ParametresAGS, ProblemeGenetique (codage de l'hybridation)

Choix d'uniformisation (v2)
---------------------------
  * UNE SEULE fonction objectif par niveau, identique pour les 3 algorithmes :
      N1 : 10000*conflits_salles + 10000*conflits_chirurgiens
           + 100*salles_differentes + 50*fragmentation
      N2 : fonction du Tabou (score en milliers) :
           8000*non_placés + 100*dépassement_bloc(min) + 1*bloc_inoccupé(min)
         + 5000*lits_en_trop + 20*variance_lits
         + 5000*places_en_trop + 20*variance_places
    -> les `score_final` de toutes les méthodes sont directement comparables.
  * Créneaux de 120 min et marge de 10 % sur chaque vacation. Les capacités d'hébergement par défaut
    (14 lits dont 2 de réserve, 10 places ambulatoires / jour) ne concernent QUE l'instance d'étude
    du niveau 1 ; l'application et le planning v28 ont leurs propres capacités (voir PARAMÈTRES).
  * Occupation d'un lit : du jour (opération - nuits_pre_op) au jour
    (opération + nuits_post_op) INCLUS (convention Tabou).
  * Horizon de plusieurs semaines (instance d'étude : une semaine + semaines de report ; interface :
    4 semaines optimisées, 52 connues du SMA). Le planning du bloc dépend de la PARITÉ de la
    semaine : cycle de 4 semaines  impaire_1 -> paire -> impaire_2 -> paire
    (« une semaine impaire sur 2 » = impaire_1 / impaire_2). Chaque `Vacation`
    porte `semaines` (types de semaine où elle a lieu). Un planning MODÈLE
    (toutes les vacations, avec leur parité) est instancié pour une semaine
    réelle avec `planning_pour_semaine(creneaux, vacations, lundi)`.
    `type_semaine(date)` donne le type d'une date.
  * Les vacations supplémentaires du Tabou (semaine +1) restent possibles via
    `Vacation.supplementaire` / `semaine_decalage`.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional


# =============================================================================
# 0. CONSTANTES
# =============================================================================

DUREE_CRENEAU_MINUTES = 120
TAUX_MARGE_VACATION = 0.10       # 10 % de chaque vacation réservé aux aléas
GRAINE_ETUDE = 42                # N1 (solution initiale commune)
GRAINE_PATIENTS = GRAINE_ETUDE + 1

TypePlage = Literal["LIBRE", "URGENCE", "INDISPONIBLE"]
NomAlgo = Literal["RS", "TABOU", "AGS"]
Niveau = Literal[1, 2]

JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Parité des semaines : cycle de 4 semaines  impaire_1, paire, impaire_2, paire.
# Les semaines impaires alternent entre impaire_1 et impaire_2 (« 1 sem. impaire sur 2 »).
TypeSemaine = Literal["paire", "impaire_1", "impaire_2"]
TYPES_SEMAINE: tuple[str, ...] = ("paire", "impaire_1", "impaire_2")
LUNDI_REFERENCE_CYCLE = date(2026, 10, 5)    # un lundi de semaine « impaire_1 » (ISO S41) ; à adapter

# Mouvement de recherche locale : suite de (identifiant, ancienne valeur, nouvelle valeur)
#   N1 : (bloc_id, ancienne_plage, nouvelle_plage)
#   N2 : (patient_id, ancienne_vacation | None, nouvelle_vacation | None)
Mouvement = tuple[tuple[int, Optional[int], Optional[int]], ...]


def minutes_entre(jour: date, heure_debut: time, heure_fin: time) -> int:
    """Durée en minutes entre deux horaires d'un même jour."""
    return int((datetime.combine(jour, heure_fin) - datetime.combine(jour, heure_debut)).total_seconds() // 60)


# =============================================================================
# 1. COMMUN
# =============================================================================

# -----------------------------------------------------------------------------
# 1.1 Données métier
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Chirurgien:
    id: int
    nom: str
    besoin_heures_semaine: float
    salles_autorisees: tuple[int, ...]
    salle_preferee: Optional[int] = None


@dataclass(frozen=True)
class Salle:
    id: int
    nom: str


@dataclass(frozen=True)
class Creneau:
    """Plage horaire élémentaire (ex. lundi 8h-10h)."""
    id: int
    jour: date
    heure_debut: time
    heure_fin: time

    @property
    def duree_minutes(self) -> int:
        return minutes_entre(self.jour, self.heure_debut, self.heure_fin)


@dataclass(frozen=True)
class PlageBloc:
    """Croisement salle x créneau : l'unité attribuée à un chirurgien au niveau 1."""
    id: int
    salle_id: int
    creneau_id: int
    type_plage: TypePlage


@dataclass(frozen=True)
class BlocAPlacer:
    """Besoin élémentaire (1 créneau) d'un chirurgien, à placer au niveau 1."""
    id: int
    chirurgien_id: int


@dataclass(frozen=True)
class Vacation:
    """
    Créneaux CONSÉCUTIFS d'un même chirurgien, même salle, même jour.
    SORTIE du niveau 1, ENTRÉE du niveau 2.
    Capacité utile = durée x (1 - taux_marge) - marge_minutes.
    """
    id: int
    chirurgien_id: int
    salle_id: int
    jour: date
    heure_debut: time
    heure_fin: time
    creneaux_ids: tuple[int, ...] = ()
    taux_marge: float = TAUX_MARGE_VACATION
    marge_minutes: int = 0
    supplementaire: bool = False       # ouverte en plus du planning régulier (Tabou)
    semaine_decalage: int = 0          # 0 = semaine étudiée, 1 = semaine suivante...
    semaines: tuple[str, ...] = TYPES_SEMAINE   # types de semaine où la vacation a lieu (défaut : toutes)

    def a_lieu(self, type_sem: str) -> bool:
        """Vrai si la vacation existe pour ce type de semaine (paire / impaire_1 / impaire_2)."""
        return type_sem in self.semaines

    @property
    def duree_minutes(self) -> int:
        return minutes_entre(self.jour, self.heure_debut, self.heure_fin)

    @property
    def capacite_utile_minutes(self) -> float:
        return max(0.0, self.duree_minutes * (1 - self.taux_marge) - self.marge_minutes)

    @property
    def debut(self) -> datetime:
        return datetime.combine(self.jour, self.heure_debut)


@dataclass(frozen=True)
class Patient:
    """
    Patient à placer au niveau 2.
    Utilisés par la fonction objectif : chirurgien_id, duree_bloc, ambulatoire,
    nuits_pre_op, nuits_post_op (et date_min pour la compatibilité).
    Les autres champs sont descriptifs (affichage, agents, ordre de décodage AGS).
    """
    id: int
    chirurgien_id: int
    duree_bloc: int                          # durée opératoire prévue (minutes)
    ambulatoire: bool
    nuits_pre_op: int = 0
    nuits_post_op: int = 0
    priorite: int = 2                        # 1 faible .. 4 urgente
    urgence: bool = False
    salle_preferentielle: Optional[int] = None
    date_min: Optional[date] = None          # pas d'intervention avant cette date
    nom: str = ""
    age: int = 0
    sexe: str = "ND"
    specialite: str = ""
    type_intervention: str = ""
    diagnostic: str = ""

    @property
    def duree_bloc_minutes(self) -> int:
        """Alias (ancien nom du Tabou)."""
        return self.duree_bloc

    @property
    def duree_minutes(self) -> int:
        """Alias (ancien nom de l'AGS de Tanguy)."""
        return self.duree_bloc


# -----------------------------------------------------------------------------
# 1.2 Instances
# -----------------------------------------------------------------------------

@dataclass
class InstanceProbleme:
    """Données du NIVEAU 1 (chirurgiens -> plages salle x créneau)."""
    chirurgiens: dict[int, Chirurgien]
    salles: dict[int, Salle]
    creneaux: dict[int, Creneau]
    plages_bloc: dict[int, PlageBloc]
    blocs_a_placer: dict[int, BlocAPlacer]
    disponibilites_chirurgiens: dict[int, set[int]] = field(default_factory=dict)
    nom: str = "instance_n1"
    cache_domaines: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class ParametresHebergement:
    """Capacités d'hébergement, constantes chaque jour."""
    lits_disponibles_par_jour: int = 14
    places_ambulatoires_par_jour: int = 10
    reserve_lits: int = 2

    @property
    def cap_lits(self) -> int:
        return self.lits_disponibles_par_jour - self.reserve_lits

    @property
    def cap_places(self) -> int:
        return self.places_ambulatoires_par_jour


@dataclass
class InstanceNiveau2:
    """Données du NIVEAU 2 (patients -> vacations)."""
    patients: dict[int, Patient]
    vacations: dict[int, Vacation]
    hebergement: ParametresHebergement = field(default_factory=ParametresHebergement)
    noms_chirurgiens: dict[int, str] = field(default_factory=dict)
    nom: str = "instance_n2"

    def copie(self) -> "InstanceNiveau2":
        """Copie dont on peut modifier les vacations (ajout de vacations supplémentaires)."""
        return InstanceNiveau2(dict(self.patients), dict(self.vacations), self.hebergement,
                               dict(self.noms_chirurgiens), self.nom)


# -----------------------------------------------------------------------------
# 1.3 Solutions
# -----------------------------------------------------------------------------

@dataclass
class SolutionPlanning:
    """Solution N1 : bloc_id -> plage_id."""
    affectations: dict[int, int]

    def copy(self) -> "SolutionPlanning":
        return SolutionPlanning(self.affectations.copy())


@dataclass
class SolutionPatients:
    """Solution N2 : patient_id -> vacation_id (None = patient non placé)."""
    affectations: dict[int, Optional[int]]

    def copy(self) -> "SolutionPatients":
        return SolutionPatients(self.affectations.copy())

    def non_places(self) -> list[int]:
        return [p for p, v in self.affectations.items() if v is None]


AffectationPatients = SolutionPatients   # alias : ancien nom du Tabou


# -----------------------------------------------------------------------------
# 1.4 Fonctions objectif (poids)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ParametresNiveau1:
    poids_conflit_salle: float = 10_000.0
    poids_conflit_chirurgien: float = 10_000.0
    poids_salles_differentes: float = 100.0
    poids_fragmentation: float = 50.0


@dataclass(frozen=True)
class PoidsNiveau2:
    """Poids de la fonction objectif N2 (ceux de l'étude Tabou)."""
    non_place: float = 8000.0
    depassement_vac: float = 100.0     # par minute au-delà de la capacité utile
    bloc_inoccupe: float = 1.0         # par minute inoccupée (vacations régulières)
    lit: float = 5000.0                # par lit x jour au-delà de la capacité
    var_lits: float = 20.0
    place: float = 5000.0
    var_places: float = 20.0


POIDS_N1 = ParametresNiveau1()
POIDS_N2 = PoidsNiveau2()


# -----------------------------------------------------------------------------
# 1.5 Évaluations (détail des scores)
# -----------------------------------------------------------------------------

@dataclass
class EvaluationPlanning:
    """Détail du score N1."""
    score_total: float
    conflits_salles: int = 0
    conflits_chirurgiens: int = 0
    salles_differentes: int = 0
    fragmentation: int = 0


@dataclass
class EvaluationNiveau2:
    """Détail du score N2. score_total = score_blocs + score_lits + score_places."""
    score_total: float
    score_blocs: float = 0.0
    score_lits: float = 0.0
    score_places: float = 0.0
    patients_non_places: int = 0
    depassement_bloc_minutes: float = 0.0
    temps_bloc_inoccupe_minutes: float = 0.0
    depassement_lits: int = 0
    depassement_places: int = 0
    variance_occupation_lits: float = 0.0
    variance_occupation_places: float = 0.0
    taux_occupation_bloc_pct: float = 0.0
    taux_occupation_lits_pct: float = 0.0
    taux_occupation_places_pct: float = 0.0
    pic_lits: int = 0
    pic_places: int = 0
    nb_vacations_supp_utilisees: int = 0
    patients_en_supp: int = 0
    minutes_en_supp: float = 0.0


# -----------------------------------------------------------------------------
# 1.6 Outils niveau 1
# -----------------------------------------------------------------------------

def creer_blocs_a_placer(chirurgiens: dict[int, Chirurgien],
                         duree_creneau_minutes: int = DUREE_CRENEAU_MINUTES) -> dict[int, BlocAPlacer]:
    """Découpe le besoin hebdomadaire de chaque chirurgien en blocs d'un créneau."""
    blocs, bloc_id = {}, 1
    for chir in chirurgiens.values():
        nb = chir.besoin_heures_semaine * 60 / duree_creneau_minutes
        if abs(nb - round(nb)) > 1e-9:
            raise ValueError(f"{chir.nom}: besoin horaire incompatible avec des créneaux de {duree_creneau_minutes} min")
        for _ in range(int(round(nb))):
            blocs[bloc_id] = BlocAPlacer(bloc_id, chir.id)
            bloc_id += 1
    return blocs


def creneaux_se_chevauchent(c1: Creneau, c2: Creneau) -> bool:
    return c1.jour == c2.jour and c1.heure_debut < c2.heure_fin and c2.heure_debut < c1.heure_fin


def plages_possibles_pour_chirurgien(instance: InstanceProbleme, chirurgien_id: int) -> list[int]:
    """Plages LIBRES, en salle autorisée, sur une disponibilité du chirurgien (mis en cache)."""
    if chirurgien_id in instance.cache_domaines:
        return instance.cache_domaines[chirurgien_id][0]
    chir = instance.chirurgiens[chirurgien_id]
    dispo = instance.disponibilites_chirurgiens.get(chirurgien_id)
    res = [pid for pid, p in instance.plages_bloc.items()
           if p.type_plage == "LIBRE"
           and p.salle_id in chir.salles_autorisees
           and (dispo is None or p.creneau_id in dispo)]
    instance.cache_domaines[chirurgien_id] = (res, frozenset(res))
    return res


def ensemble_plages_possibles(instance: InstanceProbleme, chirurgien_id: int) -> frozenset:
    plages_possibles_pour_chirurgien(instance, chirurgien_id)
    return instance.cache_domaines[chirurgien_id][1]


def evaluer_planning(instance: InstanceProbleme, solution: SolutionPlanning,
                     poids: ParametresNiveau1 = POIDS_N1) -> EvaluationPlanning:
    """Fonction objectif N1 commune (à MINIMISER)."""
    conflits_salles = conflits_chir = 0
    par_jour: dict[date, list] = {}
    par_chir: dict[int, list] = {}
    for bloc_id, plage_id in solution.affectations.items():
        chir = instance.blocs_a_placer[bloc_id].chirurgien_id
        plage = instance.plages_bloc[plage_id]
        c = instance.creneaux[plage.creneau_id]
        par_jour.setdefault(c.jour, []).append((chir, plage.salle_id, c))
        par_chir.setdefault(chir, []).append((plage.salle_id, c))

    for elems in par_jour.values():
        for i in range(len(elems)):
            ch1, s1, c1 = elems[i]
            for j in range(i + 1, len(elems)):
                ch2, s2, c2 = elems[j]
                if creneaux_se_chevauchent(c1, c2):
                    conflits_salles += s1 == s2
                    conflits_chir += ch1 == ch2

    salles_diff = frag = 0
    for elems in par_chir.values():
        salles_diff += max(0, len({s for s, _ in elems}) - 1)
        groupes: dict = {}
        for s, c in elems:
            groupes.setdefault((s, c.jour), []).append(c)
        nb = 0
        for lst in groupes.values():
            lst.sort(key=lambda x: x.heure_debut)
            nb += 1 + sum(lst[k - 1].heure_fin != lst[k].heure_debut for k in range(1, len(lst)))
        frag += max(0, nb - 1)

    score = (conflits_salles * poids.poids_conflit_salle + conflits_chir * poids.poids_conflit_chirurgien
             + salles_diff * poids.poids_salles_differentes + frag * poids.poids_fragmentation)
    return EvaluationPlanning(score, conflits_salles, conflits_chir, salles_diff, frag)


def verifier_solution_niveau1(instance: InstanceProbleme, solution: SolutionPlanning) -> list[str]:
    """Contrôle indépendant des contraintes FORTES du N1. Liste vide = solution faisable."""
    erreurs = []
    manquants = set(instance.blocs_a_placer) - set(solution.affectations)
    if manquants:
        erreurs.append(f"Blocs non affectés : {sorted(manquants)}")
    minutes: dict[int, int] = {}
    for b, pid in solution.affectations.items():
        plage = instance.plages_bloc.get(pid)
        if plage is None:
            erreurs.append(f"Bloc {b} : plage {pid} inexistante")
            continue
        cid = instance.blocs_a_placer[b].chirurgien_id
        if pid not in ensemble_plages_possibles(instance, cid):
            erreurs.append(f"Bloc {b} : plage {pid} incompatible (type, salle ou disponibilité)")
        minutes[cid] = minutes.get(cid, 0) + instance.creneaux[plage.creneau_id].duree_minutes
    ev = evaluer_planning(instance, solution)
    if ev.conflits_salles:
        erreurs.append(f"{ev.conflits_salles} conflit(s) de salle")
    if ev.conflits_chirurgiens:
        erreurs.append(f"{ev.conflits_chirurgiens} conflit(s) de chirurgien")
    for cid, chir in instance.chirurgiens.items():
        if minutes.get(cid, 0) != chir.besoin_heures_semaine * 60:
            erreurs.append(f"{chir.nom} : {minutes.get(cid, 0)} min au lieu de {chir.besoin_heures_semaine * 60:.0f}")
    return erreurs


def generer_solution_initiale_niveau1(instance: InstanceProbleme,
                                      rng: Optional[random.Random] = None) -> SolutionPlanning:
    """
    Solution initiale FAISABLE commune (backtracking, bloc le plus contraint d'abord,
    salle préférée en priorité). Utilisée comme point de départ du RS et du Tabou.
    """
    tirage = rng if rng is not None else random.Random(GRAINE_ETUDE)
    domaines = {b: list(plages_possibles_pour_chirurgien(instance, bloc.chirurgien_id))
                for b, bloc in instance.blocs_a_placer.items()}
    for d in domaines.values():
        tirage.shuffle(d)
    affectations: dict[int, int] = {}
    utilisees: set[int] = set()

    def compatible(bloc_id, plage_id):
        if plage_id in utilisees:
            return False
        chir = instance.blocs_a_placer[bloc_id].chirurgien_id
        c = instance.creneaux[instance.plages_bloc[plage_id].creneau_id]
        for b2, p2 in affectations.items():
            if instance.blocs_a_placer[b2].chirurgien_id == chir and \
                    creneaux_se_chevauchent(c, instance.creneaux[instance.plages_bloc[p2].creneau_id]):
                return False
        return True

    def chercher():
        if len(affectations) == len(instance.blocs_a_placer):
            return True
        restants = [b for b in instance.blocs_a_placer if b not in affectations]
        bloc_id = min(restants, key=lambda b: sum(compatible(b, p) for p in domaines[b]))
        chir = instance.chirurgiens[instance.blocs_a_placer[bloc_id].chirurgien_id]
        candidats = [p for p in domaines[bloc_id] if compatible(bloc_id, p)]
        candidats.sort(key=lambda p: chir.salle_preferee is not None
                       and instance.plages_bloc[p].salle_id != chir.salle_preferee)
        for p in candidats:
            affectations[bloc_id] = p
            utilisees.add(p)
            if chercher():
                return True
            utilisees.remove(p)
            del affectations[bloc_id]
        return False

    if not chercher():
        raise ValueError("Impossible de construire un planning avec les disponibilités et salles fournies.")
    return SolutionPlanning(dict(affectations))


def construire_vacations(instance: InstanceProbleme, solution: SolutionPlanning,
                         taux_marge: float = TAUX_MARGE_VACATION) -> dict[int, Vacation]:
    """PASSERELLE N1 -> N2 : regroupe les créneaux contigus (même chirurgien, salle, jour)."""
    groupes: dict[tuple, list[Creneau]] = {}
    for bloc_id, plage_id in solution.affectations.items():
        plage = instance.plages_bloc[plage_id]
        c = instance.creneaux[plage.creneau_id]
        groupes.setdefault((instance.blocs_a_placer[bloc_id].chirurgien_id, plage.salle_id, c.jour), []).append(c)

    vacations, vid = {}, 1
    for (chir, salle, jour), lst in sorted(groupes.items(), key=lambda kv: (kv[0][2], kv[0][1], kv[0][0])):
        lst.sort(key=lambda c: c.heure_debut)
        series = [[lst[0]]]
        for c in lst[1:]:
            if series[-1][-1].heure_fin == c.heure_debut:
                series[-1].append(c)
            else:
                series.append([c])
        for s in series:
            vacations[vid] = Vacation(vid, chir, salle, jour, s[0].heure_debut, s[-1].heure_fin,
                                      tuple(c.id for c in s), taux_marge=taux_marge)
            vid += 1
    return vacations


def type_semaine(jour: date) -> str:
    """Type de la semaine contenant `jour` : "paire", "impaire_1" ou "impaire_2" (cycle de 4 semaines)."""
    lundi = jour - timedelta(days=jour.weekday())
    n = ((lundi - LUNDI_REFERENCE_CYCLE).days // 7) % 4
    return ("impaire_1", "paire", "impaire_2", "paire")[n]


def planning_pour_semaine(creneaux_modele: dict[int, Creneau], vacations_modele: dict[int, Vacation],
                          lundi: date) -> tuple[dict[int, Creneau], dict[int, Vacation]]:
    """
    Instancie un planning MODÈLE pour la semaine du `lundi` donné : garde les vacations dont
    `semaines` contient le type de cette semaine et recale leurs dates (jour de semaine conservé).
    Les ids du modèle sont conservés. Résultat : (creneaux, vacations) prêts pour InstanceNiveau2.
    """
    lundi = lundi - timedelta(days=lundi.weekday())
    ts = type_semaine(lundi)

    def recaler(j: date) -> date:
        return lundi + timedelta(days=j.weekday())

    vacations = {vid: replace(v, jour=recaler(v.jour)) for vid, v in vacations_modele.items() if v.a_lieu(ts)}
    ids = {cid for v in vacations.values() for cid in v.creneaux_ids}
    creneaux = {cid: replace(c, jour=recaler(c.jour)) for cid, c in creneaux_modele.items() if cid in ids}
    return creneaux, vacations


# -----------------------------------------------------------------------------
# 1.7 Outils niveau 2
# -----------------------------------------------------------------------------

def vacations_compatibles(patient: Patient, vacations: dict[int, Vacation]) -> list[int]:
    """Vacations du chirurgien du patient (postérieures à sa date minimale éventuelle)."""
    return [vid for vid, v in vacations.items()
            if v.chirurgien_id == patient.chirurgien_id
            and (patient.date_min is None or v.jour >= patient.date_min)]


def penalite_priorite_patient(patient: Patient, vacation_id: int, vacations: dict[int, Vacation]) -> float:
    """
    Pénalise le placement tardif d'un patient selon sa priorité.

    0   = vacation la plus précoce accessible au patient
    1   = vacation la plus tardive pour un patient de priorité 4

    Les valeurs intermédiaires sont normalisées entre 0 et 1.
    """

    compatibles = vacations_compatibles(patient, vacations)

    if not compatibles or vacation_id not in compatibles:
        return 0.0

    debuts = [
        vacations[vid].debut
        for vid in compatibles
    ]

    premier = min(debuts)
    dernier = max(debuts)

    amplitude = (
        dernier - premier
    ).total_seconds()

    if amplitude <= 0:
        retard_normalise = 0.0
    else:
        retard_normalise = (
            vacations[vacation_id].debut
            - premier
        ).total_seconds() / amplitude

        retard_normalise = min(
            1.0,
            max(0.0, retard_normalise),
        )

    # Une urgence est considérée comme priorité maximale.
    priorite_effective = (
        4
        if patient.urgence
        else min(4, max(1, patient.priorite))
    )

    return (
        priorite_effective / 4.0
    ) * retard_normalise


def jours_occupation(patient: Patient, jour_operation: date) -> list[date]:
    """
    Jours où le patient occupe une ressource :
      ambulatoire -> [jour opératoire]            (place ambulatoire)
      hospitalisé -> [op - pré ; op + post] inclus (lit)
    """
    if patient.ambulatoire:
        return [jour_operation]
    debut = jour_operation - timedelta(days=patient.nuits_pre_op)
    return [debut + timedelta(days=k) for k in range(patient.nuits_pre_op + patient.nuits_post_op + 1)]


def calculer_occupation_par_jour(instance2: InstanceNiveau2, solution: SolutionPatients
                                 ) -> tuple[dict[date, int], dict[date, int]]:
    """Occupation (lits, places) jour par jour."""
    lits: dict[date, int] = {}
    places: dict[date, int] = {}
    for pid, vid in solution.affectations.items():
        if vid is None:
            continue
        p = instance2.patients[pid]
        cible = places if p.ambulatoire else lits
        for j in jours_occupation(p, instance2.vacations[vid].jour):
            cible[j] = cible.get(j, 0) + 1
    return lits, places


def variance(valeurs: list[float]) -> float:
    if not valeurs:
        return 0.0
    m = sum(valeurs) / len(valeurs)
    return sum((v - m) ** 2 for v in valeurs) / len(valeurs)


def evaluer_niveau2(instance2: InstanceNiveau2, solution: SolutionPatients,
                    poids: PoidsNiveau2 = POIDS_N2) -> EvaluationNiveau2:
    """
    Fonction objectif N2 COMMUNE (évaluation complète, référence).
    Le temps inoccupé des vacations supplémentaires n'est pas compté :
    elles ne servent qu'à absorber le surplus.
    """
    V = instance2.vacations
    charge = {vid: 0.0 for vid in V}
    non_places = patients_supp = 0
    for pid, vid in solution.affectations.items():
        if vid is None:
            non_places += 1
            continue
        charge[vid] += instance2.patients[pid].duree_bloc
        patients_supp += V[vid].supplementaire

    depassement = inoccupe = utile = cap_tot = minutes_supp = 0.0
    nb_supp = 0
    for vid, v in V.items():
        cap, ch = v.capacite_utile_minutes, charge[vid]
        if ch > cap:
            depassement += ch - cap
        if v.supplementaire:
            if ch > 0:
                nb_supp += 1
                minutes_supp += ch
            continue
        cap_tot += cap
        utile += min(ch, cap)
        inoccupe += max(0.0, cap - ch)

    lits, places = calculer_occupation_par_jour(instance2, solution)
    h = instance2.hebergement
    d_lits = sum(max(0, o - h.cap_lits) for o in lits.values())
    d_places = sum(max(0, o - h.cap_places) for o in places.values())
    v_lits, v_places = variance(list(lits.values())), variance(list(places.values()))

    s_blocs = non_places * poids.non_place + depassement * poids.depassement_vac + inoccupe * poids.bloc_inoccupe
    s_lits = d_lits * poids.lit + v_lits * poids.var_lits
    s_places = d_places * poids.place + v_places * poids.var_places

    def taux(occ, cap):
        return sum(occ.values()) / len(occ) / cap * 100 if occ and cap > 0 else 0.0

    return EvaluationNiveau2(
        score_total=s_blocs + s_lits + s_places, score_blocs=s_blocs, score_lits=s_lits, score_places=s_places,
        patients_non_places=non_places, depassement_bloc_minutes=depassement, temps_bloc_inoccupe_minutes=inoccupe,
        depassement_lits=d_lits, depassement_places=d_places,
        variance_occupation_lits=v_lits, variance_occupation_places=v_places,
        taux_occupation_bloc_pct=100 * utile / cap_tot if cap_tot else 0.0,
        taux_occupation_lits_pct=taux(lits, h.cap_lits), taux_occupation_places_pct=taux(places, h.cap_places),
        pic_lits=max(lits.values(), default=0), pic_places=max(places.values(), default=0),
        nb_vacations_supp_utilisees=nb_supp, patients_en_supp=patients_supp, minutes_en_supp=minutes_supp,
    )


class SuiviOccupation:
    """
    Occupation jour par jour d'une ressource (lits OU places) avec dépassement de
    capacité et variance tenus à jour en O(1) par jour modifié. La variance porte
    sur les jours où l'occupation est > 0 (comme evaluer_niveau2).
    """
    __slots__ = ("cap", "occ", "violation", "n", "s1", "s2")

    def __init__(self, cap: int):
        self.cap, self.occ = cap, {}
        self.violation, self.n, self.s1, self.s2 = 0, 0, 0, 0

    def modifier(self, jours, delta: int):
        occ, cap = self.occ, self.cap
        for j in jours:
            o = occ.get(j, 0)
            no = o + delta
            if o > cap:
                self.violation -= o - cap
            if no > cap:
                self.violation += no - cap
            if o > 0:
                self.n -= 1
                self.s1 -= o
                self.s2 -= o * o
            if no > 0:
                self.n += 1
                self.s1 += no
                self.s2 += no * no
                occ[j] = no
            else:
                occ.pop(j, None)

    def variance(self) -> float:
        if self.n == 0:
            return 0.0
        m = self.s1 / self.n
        return max(0.0, self.s2 / self.n - m * m)

    def peut_ajouter(self, jours) -> bool:
        return all(self.occ.get(j, 0) + 1 <= self.cap for j in jours)


class EtatNiveau2:
    """
    Solution N2 modifiable EN PLACE avec score INCRÉMENTAL (même valeur que
    evaluer_niveau2, en bien plus rapide). Utilisée par les trois algorithmes :
        etat = EtatNiveau2(instance2, affectations)
        etat.deplacer(patient_id, vacation_id | None)
        etat.score()
    """

    def __init__(self, instance2: InstanceNiveau2, affectations: Optional[dict] = None,
                 poids: PoidsNiveau2 = POIDS_N2):
        self.instance2 = instance2
        self.poids = poids
        self.patients = instance2.patients
        self.vacations = instance2.vacations
        h = instance2.hebergement
        self.lits = SuiviOccupation(h.cap_lits)
        self.places = SuiviOccupation(h.cap_places)
        self.cap = {vid: v.capacite_utile_minutes for vid, v in self.vacations.items()}
        self.charge = {vid: 0.0 for vid in self.vacations}
        self.supp = {vid for vid, v in self.vacations.items() if v.supplementaire}
        self.depassement = 0.0
        self.inoccupe = sum(c for vid, c in self.cap.items() if vid not in self.supp)
        self.non_places = len(self.patients)
        self.aff: dict[int, Optional[int]] = {pid: None for pid in self.patients}
        self._jours: dict = {}
        for pid, vid in (affectations or {}).items():
            if vid is not None:
                self.deplacer(pid, vid)

    def _jours_de(self, pid, vid):
        cle = (pid, vid)
        j = self._jours.get(cle)
        if j is None:
            j = self._jours[cle] = tuple(jours_occupation(self.patients[pid], self.vacations[vid].jour))
        return j

    def _charge(self, vid, delta):
        cap, ancien = self.cap[vid], self.charge[vid]
        nouveau = ancien + delta
        regulier = vid not in self.supp
        if ancien > cap:
            self.depassement -= ancien - cap
        elif regulier:
            self.inoccupe -= cap - ancien
        if nouveau > cap:
            self.depassement += nouveau - cap
        elif regulier:
            self.inoccupe += cap - nouveau
        self.charge[vid] = nouveau

    def deplacer(self, pid: int, nouvelle: Optional[int]):
        ancienne = self.aff[pid]
        if ancienne == nouvelle:
            return
        p = self.patients[pid]
        res = self.places if p.ambulatoire else self.lits
        if ancienne is None:
            self.non_places -= 1
        else:
            self._charge(ancienne, -p.duree_bloc)
            res.modifier(self._jours_de(pid, ancienne), -1)
        if nouvelle is None:
            self.non_places += 1
        else:
            self._charge(nouvelle, p.duree_bloc)
            res.modifier(self._jours_de(pid, nouvelle), +1)
        self.aff[pid] = nouvelle

    def peut_placer(self, pid: int, vid: int) -> bool:
        """Vrai si placer le patient dans la vacation ne dépasse AUCUNE capacité."""
        p = self.patients[pid]
        if self.charge[vid] + p.duree_bloc > self.cap[vid] + 1e-9:
            return False
        res = self.places if p.ambulatoire else self.lits
        return res.peut_ajouter(self._jours_de(pid, vid))

    def score_blocs(self) -> float:
        w = self.poids
        return self.non_places * w.non_place + self.depassement * w.depassement_vac + self.inoccupe * w.bloc_inoccupe

    def score_lits(self) -> float:
        return self.lits.violation * self.poids.lit + self.lits.variance() * self.poids.var_lits

    def score_places(self) -> float:
        return self.places.violation * self.poids.place + self.places.variance() * self.poids.var_places

    def score(self) -> float:
        return self.score_blocs() + self.score_lits() + self.score_places()

    def solution(self) -> SolutionPatients:
        return SolutionPatients(dict(self.aff))


def construire_affectation_initiale(instance2: InstanceNiveau2,
                                    rng: Optional[random.Random] = None) -> SolutionPatients:
    """
    Glouton liste + best-fit (Tabou) : patients des chirurgiens ayant le moins de
    vacations d'abord, ambulatoires d'abord, plus longs d'abord ; chaque patient va
    dans la vacation compatible la plus remplie qui respecte TOUTES les capacités
    (vacations régulières avant les supplémentaires). Sinon : non placé.
    """
    tirage = rng if rng is not None else random.Random(GRAINE_PATIENTS)
    V = instance2.vacations
    nb_vac: dict[int, int] = {}
    for v in V.values():
        nb_vac[v.chirurgien_id] = nb_vac.get(v.chirurgien_id, 0) + 1
    ordre = list(instance2.patients)
    tirage.shuffle(ordre)
    ordre.sort(key=lambda pid: (nb_vac.get(instance2.patients[pid].chirurgien_id, 0),
                                not instance2.patients[pid].ambulatoire,
                                -instance2.patients[pid].duree_bloc))
    etat = EtatNiveau2(instance2)
    for pid in ordre:
        meilleure, cle_min = None, None
        for vid in vacations_compatibles(instance2.patients[pid], V):
            if not etat.peut_placer(pid, vid):
                continue
            reste = etat.cap[vid] - etat.charge[vid] - instance2.patients[pid].duree_bloc
            cle = (V[vid].supplementaire, V[vid].semaine_decalage, reste)
            if cle_min is None or cle < cle_min:
                cle_min, meilleure = cle, vid
        if meilleure is not None:
            etat.deplacer(pid, meilleure)
    return etat.solution()


def construire_meilleure_affectation_initiale(instance2: InstanceNiveau2, nb_essais: int = 40,
                                              graine: int = GRAINE_PATIENTS) -> SolutionPatients:
    """Multi-départ du glouton : solution initiale N2 COMMUNE au RS et au Tabou."""
    meilleure, meilleur_score = None, float("inf")
    for k in range(nb_essais):
        cand = construire_affectation_initiale(instance2, random.Random(graine + k))
        s = EtatNiveau2(instance2, cand.affectations).score()
        if s < meilleur_score:
            meilleure, meilleur_score = cand, s
    return meilleure


# -----------------------------------------------------------------------------
# 1.8 Interface commune
# -----------------------------------------------------------------------------

class ProblemeOptimisation(ABC):
    """
    Contrat minimal commun aux trois algorithmes. Chaque famille l'étend :
    voisin() pour le RS, voisinage() pour le Tabou, opérateurs génétiques pour l'AGS.
    """
    niveau: Niveau = 1

    @abstractmethod
    def solution_initiale(self, rng: random.Random):
        """Solution complète de départ."""

    @abstractmethod
    def evaluer(self, solution) -> float:
        """Coût à MINIMISER (fonction objectif commune du niveau)."""


# -----------------------------------------------------------------------------
# 1.9 Données de l'étude (instances de référence COMMUNES)
# -----------------------------------------------------------------------------

def construire_instance_etude(disponibilites_elargies: bool = True) -> InstanceProbleme:
    """
    Instance N1 de référence (8 chirurgiens, 3 salles, semaine du 21/09/2026,
    créneaux de 2 h : 8-10, 10-12, 13-15, 15-17 ; salle 3 réservée aux urgences
    de 8 h à 10 h). disponibilites_elargies=True (défaut, version Tabou) : Dr C,
    D, F et G ont en plus un créneau 15h-17h un autre jour.
    """
    chirurgiens = {
        1: Chirurgien(1, "Dr A", 14, (1, 2), 1),
        2: Chirurgien(2, "Dr B", 14, (1, 2), 2),
        3: Chirurgien(3, "Dr C", 8, (2, 3), 3),
        4: Chirurgien(4, "Dr D", 8, (1, 3), 3),
        5: Chirurgien(5, "Dr E", 14, (1, 2, 3), None),
        6: Chirurgien(6, "Dr F", 8, (2, 3), 2),
        7: Chirurgien(7, "Dr G", 8, (1,), 1),
        8: Chirurgien(8, "Dr H", 16, (1, 2, 3), None),
    }
    salles = {1: Salle(1, "Salle 1"), 2: Salle(2, "Salle 2"), 3: Salle(3, "Salle 3")}
    jours = [date(2026, 9, 21) + timedelta(days=k) for k in range(5)]
    horaires = [(time(8), time(10)), (time(10), time(12)), (time(13), time(15)), (time(15), time(17))]

    creneaux, par_jour, cid = {}, [], 1
    for j in jours:
        ids = []
        for hd, hf in horaires:
            creneaux[cid] = Creneau(cid, j, hd, hf)
            ids.append(cid)
            cid += 1
        par_jour.append(ids)
    lundi, mardi, mercredi, jeudi, vendredi = par_jour

    plages, pid = {}, 1
    for s in salles:
        for c_id, c in creneaux.items():
            urgence = s == 3 and c.heure_debut == time(8)
            plages[pid] = PlageBloc(pid, s, c_id, "URGENCE" if urgence else "LIBRE")
            pid += 1

    e = disponibilites_elargies
    dispo = {
        1: set(lundi + mardi), 2: set(lundi + mardi),
        3: set(mercredi + ([mardi[3]] if e else [])),
        4: set(mercredi + ([lundi[3]] if e else [])),
        5: set(jeudi + vendredi),
        6: set(jeudi + ([vendredi[3]] if e else [])),
        7: set(vendredi + ([jeudi[3]] if e else [])),
        8: set(lundi + mardi + mercredi + jeudi + vendredi),
    }
    return InstanceProbleme(chirurgiens, salles, creneaux, plages, creer_blocs_a_placer(chirurgiens), dispo,
                            nom="etude" + ("_elargie" if e else ""))


SPECIALITES_PAR_CHIRURGIEN = {
    1: "Orthopédie", 2: "Digestif", 3: "ORL", 4: "Urologie",
    5: "Gynécologie", 6: "Vasculaire", 7: "Ophtalmologie", 8: "Chirurgie générale",
}
PRENOMS = ["Léo", "Emma", "Hugo", "Alice", "Noah", "Léa", "Jules", "Chloé", "Louis", "Zoé",
           "Gabriel", "Inès", "Adam", "Jade", "Raphaël", "Louise", "Arthur", "Anna", "Nathan", "Camille",
           "Sacha", "Mila", "Tom", "Rose", "Ethan", "Iris", "Marius", "Nina"]


def generer_patients_etude(vacations: dict[int, Vacation], graine: int = GRAINE_PATIENTS,
                           charge_min: float = 0.90, charge_max: float = 1.10) -> dict[int, Patient]:
    """
    Générateur de patients COMMUN (logique du Tabou) : pour chaque chirurgien, des
    patients jusqu'à `charge_min`..`charge_max` fois la durée de ses vacations
    (donc un peu plus que la capacité utile : il y aura du surplus à gérer).
    Priorité / urgence (distribution de l'AGS de Tanguy) tirées avec un second
    générateur pour ne pas modifier les tirages d'origine.
    """
    tirage = random.Random(graine)
    tirage_prio = random.Random(graine + 1000)
    capacite: dict[int, float] = {}
    for v in vacations.values():
        if not v.supplementaire:
            capacite[v.chirurgien_id] = capacite.get(v.chirurgien_id, 0) + v.duree_minutes

    durees = [30, 45, 60, 75, 90, 105, 120, 150]
    patients, pid = {}, 1
    for chir_id, cap in sorted(capacite.items()):
        objectif = cap * tirage.uniform(charge_min, charge_max)
        cumul = 0.0
        while cumul < objectif:
            restant = objectif - cumul
            if restant < durees[0]:
                break
            duree = tirage.choice([d for d in durees if d <= restant + 15] or [durees[0]])
            amb = tirage.random() < 0.40
            if amb:
                pre, post = 0, 0
            else:
                pre = 1 if tirage.random() < 0.30 else 0
                post = tirage.choice([1, 1, 2, 2, 3])
            nom = tirage.choice(PRENOMS)
            age, sexe = tirage.randint(5, 90), tirage.choice(["F", "M"])
            prio = tirage_prio.choices([1, 2, 3, 4], weights=[0.15, 0.50, 0.25, 0.10])[0]
            urg = tirage_prio.random() < 0.05
            patients[pid] = Patient(
                id=pid, chirurgien_id=chir_id, duree_bloc=duree, ambulatoire=amb,
                nuits_pre_op=pre, nuits_post_op=post, priorite=4 if urg else prio, urgence=urg,
                nom=nom, age=age, sexe=sexe, specialite=SPECIALITES_PAR_CHIRURGIEN.get(chir_id, ""))
            cumul += duree
            pid += 1
    return patients


def construire_instance_niveau2(instance1: InstanceProbleme, solution1: SolutionPlanning,
                                graine_patients: int = GRAINE_PATIENTS,
                                hebergement: ParametresHebergement = ParametresHebergement(),
                                nom: str = "n2") -> InstanceNiveau2:
    """Instance N2 à partir d'un planning N1 : vacations (marge 10 %) + patients générés."""
    vacations = construire_vacations(instance1, solution1)
    patients = generer_patients_etude(vacations, graine_patients)
    return InstanceNiveau2(patients, vacations, hebergement,
                           {cid: c.nom for cid, c in instance1.chirurgiens.items()}, nom)


def instance_niveau2_reference() -> tuple[InstanceProbleme, InstanceNiveau2]:
    """
    Instance N2 COMMUNE aux trois algorithmes, pour une comparaison équitable :
    vacations issues du planning N1 initial commun (backtracking, graine 42), puis
    patients générés (graine 43). Toujours identique d'un notebook à l'autre.
    """
    inst1 = construire_instance_etude()
    sol1 = generer_solution_initiale_niveau1(inst1, random.Random(GRAINE_ETUDE))
    return inst1, construire_instance_niveau2(inst1, sol1, nom="n2_reference")


# =============================================================================
# 2. AGS — ALGORITHME GÉNÉTIQUE SIMPLE
# =============================================================================

Individu = list   # chromosome : liste de gènes (N1 : plage par bloc ; N2 : vacation par patient)


@dataclass(frozen=True)
class ParametresAGS:
    taille_population: int = 50
    generations: int = 100
    taux_croisement: float = 0.8
    taux_mutation: float = 0.2
    taille_tournoi: int = 3
    elites: int = 2
    graine: int = GRAINE_ETUDE


class ProblemeGenetique(ProblemeOptimisation):
    """Problème codé en liste de gènes, optimisable par l'AGS."""

    @abstractmethod
    def individu_aleatoire(self, rng: random.Random) -> Individu: ...

    @abstractmethod
    def vers_solution(self, individu: Individu): ...

    @abstractmethod
    def croiser(self, parent1: Individu, parent2: Individu, rng: random.Random) -> tuple[Individu, Individu]: ...

    @abstractmethod
    def muter(self, individu: Individu, rng: random.Random) -> Individu: ...

    def cout(self, individu: Individu) -> float:
        return self.evaluer(self.vers_solution(individu))

    def solution_initiale(self, rng: random.Random):
        return self.vers_solution(self.individu_aleatoire(rng))