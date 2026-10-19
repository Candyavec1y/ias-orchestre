# -*- coding: utf-8 -*-
"""
sma/sma_urgences.py — Système MULTI-AGENT de gestion des aléas du bloc opératoire (Mesa >= 3.0)
==================================================================================================

Ce fichier ne contient QUE le SMA. Il réutilise, sans les recopier :
    commun/structures_communes.py               Patient, Vacation, InstanceNiveau2, glouton N2...
    planning_vacations/planning_vacations_v28.py planning réel du bloc (vacations, plages URGENCE / LIBRE)

Le SMA corrige EN TEMPS RÉEL le planning du niveau 2 (patient -> vacation, sortie des métaheuristiques)
quand un aléa survient, en le modifiant le moins possible.

Aléas
-----
    ArriveeUrgence(heure, patient, gravite)     gravité : "vitale" (1 h), "urgente" (6 h), "differable" (24 h)
    PanneAscenseur(heure, "ML1", fin_estimee)   le monte-lit ne permet plus de monter au bloc
    ProlongationPanne(heure, "ML1", fin_estimee)
    FinPanne(heure, "ML1")                      (sinon la logistique constate seule la fin à l'heure estimée)

Agents (messages FIPA-ACL, protocole Contract Net)
------
    AgentTriage        gravité -> délai maximal ; chirurgiens compétents (même spécialité + chirurgien d'urgence)
    AgentRegulation    coordinateur : appels d'offres, validation, décision, replacement, liste d'attente, rattrapage
    AgentSalle (x N)   ordre de passage de SES créneaux ; propose et chiffre (insérer, décaler, déprogrammer)
    AgentChirurgien    son agenda ; refuse s'il est déjà au bloc, signale un rappel d'astreinte
    AgentHebergement   lits et places ambulatoires
    AgentLogistique    ascenseurs ; fenêtres où le brancardage est impossible
    AgentGarde         planning de garde (soirs, nuits, jours sans programme) : prend toute urgence que le
                       programme ne peut pas absorber, puis PRÉVIENT le système (INFORM à la régulation)
    AgentOptimisation  réoptimisation GLOBALE du programme restant (toutes salles, tout l'horizon) par vos
                       métaheuristiques ; propose, ne décide pas (optimisation_sma.py)

Architecture HYBRIDE (optimisation_sma.py, metaheuristiques_sma.py -> metaheuristiques/hybridation.py)
--------------------
    Cas B, réaction immédiate : chaque AgentSalle chiffre ses propositions par un glouton, puis les améliore
        localement (ordre de passage + patients reportés dans son créneau) par une métaheuristique courte
        (`methode_locale`, `budget_local_s`) ; il garde le glouton si la recherche ne fait pas mieux.
    Cas A, qualité globale : après chaque aléa, la Régulation envoie l'état du programme à l'AgentOptimisation
        (`optimisation_globale`, `budget_global_s`), qui réaffecte les patients non gelés aux créneaux en démarrage
        à chaud ; le plan n'est appliqué que s'il améliore le score ET passe le contrôle GROUPÉ des agents
        Chirurgien et Hébergement (retraits puis ajouts, en deux phases).
    Sur le site, les deux optimisations sont désactivées (rejeu de tous les événements à chaque affichage) ;
    l'optimisation globale y reste disponible à la demande (Administration).

Règles
------
  * AUCUN transfert vers un autre établissement, AUCUN refus : toute urgence reçue est programmée,
    soit dans le programme (vacations + plages URGENCE), soit dans le planning de garde.
  * Les heures du programme restent une contrainte dure (pas d'heures supplémentaires).
  * Planning de garde (HYPOTHÈSE réglable dans ParametresSMA) : une salle, une équipe, à partir de 18 h les jours
    de programme et toute la journée les autres jours ; pour une urgence VITALE l'équipe de garde est rappelée
    tout de suite (`garde_immediate`).
  * Échelle d'escalade pour une urgence (le premier niveau qui donne un plan DANS LE DÉLAI est retenu) :
        0  insertion en DÉCALANT les patients programmés (aucun report)
        1  + REPORT de patients programmés à un autre jour (au plus `max_deprogrammations`, replacés ensuite)
        2  + reports sans plafond, éviction d'urgences de gravité strictement inférieure
        3  ATTENTE : plan hors délai accepté si l'incision a lieu avant délai + tolérance (« quelques heures »)
        4  GARDE : l'urgence est confiée au planning de garde (ou au programme si c'est plus tôt), message au
           système ; alerte au médecin régulateur si le délai est dépassé (décision humaine).
  * Les Salles reçoivent dans l'appel d'offres un instantané des agendas des chirurgiens : elles ne
    proposent que des horaires où le chirurgien est libre (les agents Chirurgien valident toujours).

Utilisation
-----------
    from datetime import date, datetime
    from sma_urgences import *
    i1, i2 = construire_instances_v28(date(2026, 10, 12))          # planning v28 + patients, 2 semaines
    modele = BlocOperatoire.depuis_v28(date(2026, 10, 12), instances=(i1, i2),
                                       solution=ma_solution_N2)    # ou None : glouton commun
    p = patient_urgent(9001, ID_PAR_NOM["CT"], 60, specialite="Orthopédie", nuits_post_op=1)
    modele.planifier(ArriveeUrgence(datetime(2026, 10, 13, 9, 40), p, gravite="urgente"))
    modele.planifier(PanneAscenseur(datetime(2026, 10, 13, 10, 15), "ML1", datetime(2026, 10, 13, 13, 0)))
    modele.executer_jusqu_a(datetime(2026, 10, 13, 20, 0))
    modele.afficher_jour(date(2026, 10, 13)); modele.afficher_bilan()

Scénarios prêts à l'emploi : sma/scenarios_sma.py
"""
from __future__ import annotations

import functools
import json
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional, Union

import mesa

# --- accès aux fichiers du dépôt (planning_vacations/ contient planning_vacations_v28.py et structures_communes.py)
_RACINE = Path(__file__).resolve().parents[1]
for _dossier in (_RACINE / "planning_vacations", _RACINE / "metaheuristiques"):
    if _dossier.is_dir() and str(_dossier) not in sys.path:
        sys.path.append(str(_dossier))

import planning_vacations_v28 as V28
from parametres import (CHARGE_GENERATEUR, COUT_LIT_EN_TROP, GRAINE_MESA, NB_SEMAINES_SCENARIOS_SMA,  # noqa: E402
                        PAS_GRAINE_SEMAINE)
from structures_communes import (
    GRAINE_PATIENTS, HEBERGEMENT_SITE, JOURS_FR, POIDS_N2, Chirurgien, InstanceNiveau2, InstanceProbleme,
    ParametresHebergement, Patient,
    PlageBloc, SolutionPatients, construire_meilleure_affectation_initiale, generer_patients_etude,
    jours_occupation, type_semaine,
)

MIN = timedelta(minutes=1)
INFAISABLE = 1e9          # plan hors des heures du programme (pas d'heures supplémentaires) : écarté


# =============================================================================
# 0. PASSERELLE PLANNING v28 -> SMA
# =============================================================================
# * Les vacations du pseudo-chirurgien URGENCE (id 900) deviennent des plages "URGENCE" où le SMA insère les
#   urgences ; elles sont tenues par un « chirurgien d'urgence » anonyme (le fichier ne dit pas qui opère).
# * Les plages LIBRE (id 901) sont ignorées ; les patients ne sont générés que pour les vrais chirurgiens.
# * Plusieurs semaines : les ids du modèle v28 sont décalés de 100 par semaine.
# * Spécialités : HYPOTHÈSE reprise du jeu de test, à compléter.

ID_CHIR_URGENCE = V28.ID_URGENCE          # 900
ID_EQUIPE_GARDE = 950                      # équipe du planning de garde (hors programme)
ID_SALLE_GARDE = 0                         # salle de garde (hors des salles du programme)
ID_FENETRE_GARDE = 0
ID_PAR_NOM = V28.ID_PAR_NOM                # code praticien -> id (ex. ID_PAR_NOM["CT"])
DECALAGE_ID_SEMAINE = 100

# HYPOTHÈSE (jeu de test) — à compléter dès que les spécialités réelles sont connues
# Tous les praticiens du planning appartiennent au MÊME service (orthopédie-traumatologie) : ils sont tous compétents
# pour les patients du service (urgences, replacements, confrères). Calculé à la volée : un praticien ajouté au
# planning des vacations par l'administrateur fait aussi partie du service.
SPECIALITE_SERVICE = "Orthopédie-traumatologie"


def specialite_de(nom: str) -> str:
    """Spécialité d'un praticien (code du planning) ; "" pour URGENCE / LIBRE ou un code inconnu."""
    pid = V28.ID_PAR_NOM.get(nom)
    return SPECIALITE_SERVICE if pid is not None and pid not in (V28.ID_URGENCE, V28.ID_LIBRE) else ""


def specialites_par_id() -> dict[int, str]:
    return {pid: SPECIALITE_SERVICE for nom, pid in V28.ID_PAR_NOM.items() if specialite_de(nom)}


SPECIALITES_V28 = {nom: specialite_de(nom) for nom in V28.ID_PAR_NOM if specialite_de(nom)}   # (compatibilité)


def construire_instances_v28(lundi: date, nb_semaines: int = NB_SEMAINES_SCENARIOS_SMA,
                             patients: Optional[dict] = None, graine: int = GRAINE_PATIENTS,
                             hebergement: ParametresHebergement = HEBERGEMENT_SITE,
                             charges: Optional[tuple] = None, format_nom: str = "Patient {:03d}"
                             ) -> tuple[InstanceProbleme, InstanceNiveau2]:
    """Instances N1 / N2 du planning réel v28 sur `nb_semaines` à partir de `lundi`. Sans `patients`, les patients
    sont générés semaine par semaine par generer_patients_etude (graine + PAS_GRAINE_SEMAINE x k, date au plus tôt =
    lundi de la semaine) ; `charges` = bornes (min, max) de charge par semaine (défaut : CHARGE_GENERATEUR pour
    toutes ; au-delà de la liste, la dernière valeur). Utilisé par le SMA, l'interface (programme de démonstration)
    et l'hybridation (--instance v28)."""
    lundi = lundi - timedelta(days=lundi.weekday())
    spe = specialites_par_id()
    creneaux, plages, vacations, dispo = {}, {}, {}, {}
    minutes: dict[int, int] = {}
    patients_generes, pid = {}, 1
    for k in range(nb_semaines):
        lundi_k = lundi + timedelta(weeks=k)
        cr_k, vac_k, _ = V28.construire_semaine(lundi_k)
        dec = k * DECALAGE_ID_SEMAINE
        vac_reelles = {}
        for vid, v in vac_k.items():
            c = cr_k[v.creneaux_ids[0]]
            nid = vid + dec
            creneaux[nid] = replace(c, id=nid)
            if v.chirurgien_id == V28.ID_LIBRE:
                continue
            if v.chirurgien_id == ID_CHIR_URGENCE:
                plages[nid] = PlageBloc(nid, v.salle_id, nid, "URGENCE")
                dispo.setdefault(ID_CHIR_URGENCE, set()).add(nid)
                continue
            nv = replace(v, id=nid, creneaux_ids=(nid,))
            vacations[nid] = vac_reelles[nid] = nv
            plages[nid] = PlageBloc(nid, v.salle_id, nid, "LIBRE")      # plage occupée par cette vacation
            dispo.setdefault(v.chirurgien_id, set()).add(nid)
            minutes[v.chirurgien_id] = minutes.get(v.chirurgien_id, 0) + v.duree_minutes
        if patients is None:
            # patients de la semaine k : uniquement pour les vrais chirurgiens, pas avant ce lundi
            cmin, cmax = (charges or (CHARGE_GENERATEUR,))[min(k, len(charges or (CHARGE_GENERATEUR,)) - 1)]
            for p in generer_patients_etude(vac_reelles, graine + PAS_GRAINE_SEMAINE * k, cmin, cmax).values():
                patients_generes[pid] = replace(p, id=pid, date_min=lundi_k, nom=format_nom.format(pid),
                                                specialite=spe.get(p.chirurgien_id, ""))
                pid += 1

    chirurgiens = {}
    for cid in sorted(minutes):
        _, salles_aut, pref = (None, *V28._SALLES_PREF[cid])
        chirurgiens[cid] = Chirurgien(cid, V28.NOM_PAR_ID[cid], minutes[cid] / 60 / nb_semaines, salles_aut, pref)
    salles_urg = tuple(sorted({p.salle_id for p in plages.values() if p.type_plage == "URGENCE"}))
    chirurgiens[ID_CHIR_URGENCE] = Chirurgien(ID_CHIR_URGENCE, "Chir. urgence", 0.0, salles_urg, None)

    instance1 = InstanceProbleme(chirurgiens, dict(V28.SALLES), creneaux, plages, {}, dispo,
                                 nom=f"v28_{lundi}_{nb_semaines}sem")
    instance2 = InstanceNiveau2(patients if patients is not None else patients_generes, vacations, hebergement,
                                {cid: c.nom for cid, c in chirurgiens.items()},
                                nom=f"v28_{type_semaine(lundi)}_{lundi}_{nb_semaines}sem")
    return instance1, instance2


def solution_n2_par_defaut(instance2: InstanceNiveau2) -> SolutionPatients:
    """En attendant la solution hybride : glouton multi-départ commun (structures_communes)."""
    return construire_meilleure_affectation_initiale(instance2)


# =============================================================================
# 1. PARAMÈTRES
# =============================================================================

@dataclass(frozen=True)
class Gravite:
    nom: str
    delai_max_min: int          # délai maximal arrivée -> incision
    preparation_min: int        # bilan / préparation avant de pouvoir monter au bloc
    poids_attente: float        # coût par minute d'attente
    tolerance_min: int = 0      # attente acceptée AU-DELÀ du délai avant de passer au planning de garde
    rang: int = 0               # 3 vitale > 2 urgente > 1 différable (éviction d'une urgence moins grave)

    def limite(self, arrivee: datetime) -> datetime:
        return arrivee + self.delai_max_min * MIN

    def limite_acceptable(self, arrivee: datetime) -> datetime:
        return arrivee + (self.delai_max_min + self.tolerance_min) * MIN


# HYPOTHÈSE à valider avec l'hôpital : tolérances (« une urgence peut attendre quelques heures »)
GRAVITES = {
    "vitale": Gravite("vitale", 60, 15, 100.0, tolerance_min=60, rang=3),
    "urgente": Gravite("urgente", 360, 30, 10.0, tolerance_min=180, rang=2),
    "differable": Gravite("differable", 24 * 60, 60, 1.0, tolerance_min=240, rang=1),
}

NIVEAUX_ESCALADE = {0: "insertion avec décalages", 1: "+ reports d'autres patients",
                    2: "+ reports sans plafond / éviction d'une urgence moins grave",
                    3: "attente au-delà du délai (tolérance)", 4: "au plus tôt : planning de garde ou programme"}


@dataclass(frozen=True)
class ParametresSMA:
    pas_minutes: int = 5                # durée d'un pas Mesa
    # --- logistique ---
    transfert_min: int = 20             # brancardage chambre/urgences -> bloc
    sspi_min: int = 60                  # salle de réveil avant retour en chambre
    avance_max_min: int = 60            # avance maximale d'une intervention (patient convoqué 1 h avant)
    preparation_rattrapage_min: int = 30  # délai pour faire descendre un patient qu'on avance
    # --- coûts (à minimiser) ---
    c_decalage_min: float = 1.0         # par minute de retard, x priorité
    c_avance_min: float = 0.5           # par minute d'avance, x priorité
    c_retention_sspi_min: float = 2.0   # minute bloquée en salle de réveil (ascenseur)
    c_deprogrammation: float = 2000.0   # x priorité
    c_changement_chirurgien: float = 300.0   # patient programmé repris par un confrère
    c_astreinte: float = 500.0          # chirurgien rappelé hors de ses jours de présence
    c_lit_reserve: float = 300.0
    c_lit_depassement: float = COUT_LIT_EN_TROP   # même valeur que PoidsNiveau2.lit (commun/parametres.py)
    c_report_jour: float = 100.0        # par jour de report, x priorité
    max_deprogrammations: int = 3       # plafond des reports au niveau 1 de l'escalade (aucun plafond au niveau 2)
    propositions_par_salle: int = 4
    # --- planning de garde (HYPOTHÈSE : une salle de garde, une équipe, hors heures du programme) ---
    garde_soir: time = time(18, 0)      # les jours de programme, la garde commence à...
    garde_matin: time = time(8, 0)      # ... et se termine le lendemain à
    garde_permanente: bool = False      # True : la salle de garde fonctionne aussi pendant la journée
    # --- architecture hybride : vos métaheuristiques (metaheuristiques/hybridation.py) ---
    # modes : "RS seul" | "TABOU seul" | "AGS seul" | "memetique" | "AGS>RS>TABOU" | "RS>AGS>TABOU"
    methode_locale: Optional[str] = "TABOU seul"  # cas B, agents Salle ("glouton" ou None : pas d'optimisation locale)
    budget_local_s: float = 0.02                  # secondes par créneau et par appel d'offres (temps réel)
    optimisation_globale: Optional[str] = "memetique"  # cas A, agent Optimisation (None : pas de réoptimisation)
    budget_global_s: float = 1.0                  # secondes par réoptimisation globale
    gain_min_global: float = 50.0                 # gain minimal pour modifier le programme
    gel_optimisation_min: int = 60                # patients qui commencent dans l'heure : gelés (déjà convoqués)
    c_stabilite: float = 20.0                     # coût par patient déplacé par l'optimisation globale
    capturer_problemes: bool = False              # garde les problèmes posés (script de comparaison)
    garde_immediate: tuple[str, ...] = ("vitale",)   # gravités pour lesquelles l'équipe de garde est rappelée
                                                     # immédiatement, même pendant les heures du programme


@dataclass(frozen=True)
class Ascenseur:
    id: str
    nom: str
    etages: tuple[int, ...]
    monte_lit: bool


@dataclass(frozen=True)
class Batiment:
    etage_bloc: int = 1
    etage_hospitalisation: int = 2
    etage_ambulatoire: int = 1          # unité ambulatoire au niveau du bloc
    etage_urgences: int = 0
    ascenseurs: tuple[Ascenseur, ...] = (
        Ascenseur("ML1", "Monte-lit 1", (0, 1, 2, 3), True),
        Ascenseur("V1", "Ascenseur visiteurs", (0, 1, 2, 3), False),
    )

    def route(self, origine: str) -> Optional[tuple[int, int]]:
        etage = {"chambre": self.etage_hospitalisation, "urgences": self.etage_urgences,
                 "ambulatoire": self.etage_ambulatoire}[origine]
        return None if etage == self.etage_bloc else (etage, self.etage_bloc)


# =============================================================================
# 2. DONNÉES
# =============================================================================

@dataclass(frozen=True)
class Fenetre:
    """Heures du planning dans une salle : une vacation (id > 0) ou une plage d'urgence (id < 0)."""
    id: int
    salle_id: int
    debut: datetime
    fin: datetime
    chirurgien_id: Optional[int]        # None pour une plage d'urgence
    capacite_utile_min: float           # charge programmable hors aléas (marge de 10 %)

    @property
    def jour(self) -> date:
        return self.debut.date()

    @property
    def urgence(self) -> bool:
        return self.chirurgien_id is None


@dataclass
class Intervention:
    patient: Patient                    # patient.chirurgien_id = chirurgien qui OPÈRE
    salle_id: int
    debut: datetime
    fenetre_id: int
    debut_initial: Optional[datetime] = None
    urgence: bool = False
    chirurgien_initial: Optional[int] = None
    gravite: Optional[str] = None       # pour une urgence insérée : "vitale" / "urgente" / "differable"

    def __post_init__(self):
        if self.debut_initial is None:
            self.debut_initial = self.debut
        if self.chirurgien_initial is None:
            self.chirurgien_initial = self.patient.chirurgien_id

    pid = property(lambda s: s.patient.id)
    chirurgien_id = property(lambda s: s.patient.chirurgien_id)
    duree = property(lambda s: timedelta(minutes=s.patient.duree_bloc))
    fin = property(lambda s: s.debut + s.duree)

    @property
    def origine(self) -> str:
        if self.urgence:
            return "urgences"
        return "ambulatoire" if self.patient.ambulatoire else "chambre"

    def copie(self, **modif) -> "Intervention":
        return replace(self, **modif)


@dataclass
class Plan:
    """Proposition d'une salle : nouvel ordonnancement d'un créneau du planning."""
    salle_id: int
    fenetre_id: int
    jour: date
    placements: dict[int, datetime]
    ajouts: list[Intervention] = field(default_factory=list)
    retraits: list[int] = field(default_factory=list)
    cout: float = 0.0
    detail: dict[str, float] = field(default_factory=dict)
    hors_delai: bool = False
    debut_urgence: Optional[datetime] = None
    retenus_sspi: list[int] = field(default_factory=list)
    resume: str = ""

    def signature(self):
        return (self.salle_id, self.fenetre_id, tuple(sorted(self.placements.items())), tuple(sorted(self.retraits)),
                tuple(sorted((a.pid, a.chirurgien_id) for a in self.ajouts)))


# --- événements ---------------------------------------------------------------

@dataclass
class ArriveeUrgence:
    heure: datetime
    patient: Patient
    gravite: Optional[str] = None


@dataclass
class PanneAscenseur:
    heure: datetime
    ascenseur: str
    fin_estimee: Optional[datetime] = None


@dataclass
class ProlongationPanne:
    heure: datetime
    ascenseur: str
    fin_estimee: datetime


@dataclass
class FinPanne:
    heure: datetime
    ascenseur: str


Evenement = Union[ArriveeUrgence, PanneAscenseur, ProlongationPanne, FinPanne]


def patient_urgent(id: int, chirurgien_id: int, duree_bloc: int, *, specialite: str = "", ambulatoire: bool = False,
                   nuits_post_op: int = 2, nom: str = "", diagnostic: str = "", age: int = 40,
                   type_intervention: str = "") -> Patient:
    """Patient urgent (priorité 4). `chirurgien_id` : chirurgien qui l'a vu aux urgences (il peut
    être opéré par un autre chirurgien de la même spécialité, ou par le chirurgien d'urgence).
    La gravité (vitale / urgente / differable) se donne dans ArriveeUrgence : le Patient commun
    (structures_communes) n'a pas de champ score_urgence."""
    return Patient(id=id, chirurgien_id=chirurgien_id, duree_bloc=duree_bloc, ambulatoire=ambulatoire,
                   nuits_pre_op=0, nuits_post_op=0 if ambulatoire else nuits_post_op, priorite=4, urgence=True,
                   nom=nom, age=age, specialite=specialite, diagnostic=diagnostic,
                   type_intervention=type_intervention)


# =============================================================================
# 3. OUTILS TEMPORELS
# =============================================================================

def chevauche(a1, b1, a2, b2) -> bool:
    return a1 < b2 and a2 < b1


def premier_transfert_possible(debut: datetime, fenetres, duree_tr: int) -> datetime:
    """Plus petite heure >= debut telle que le brancardage [debut - tr ; debut] évite les pannes."""
    tr, change = duree_tr * MIN, True
    while change:
        change = False
        for a, b in fenetres:
            if chevauche(debut - tr, debut, a, b):
                debut, change = b + tr, True
    return debut


def premier_debut_possible(debut: datetime, duree: timedelta, fenetres, duree_tr: int,
                           occupations=()) -> datetime:
    """Plus petite heure >= debut où le brancardage évite les pannes ET où le chirurgien est libre
    pendant [debut ; debut + duree[ (occupations = intervalles déjà pris dans son agenda)."""
    change = True
    while change:
        change = False
        debut = premier_transfert_possible(debut, fenetres, duree_tr)
        for a, b in occupations:
            if chevauche(debut, debut + duree, a, b):
                debut, change = b, True
    return debut


def retention_sspi(fin: datetime, fenetres, p: ParametresSMA) -> float:
    """Minutes passées en salle de réveil à attendre le monte-lit."""
    retour = attente = fin + p.sspi_min * MIN
    for a, b in sorted(fenetres):
        if chevauche(attente, attente + p.transfert_min * MIN, a, b):
            attente = b
    return (attente - retour) / MIN


def minutes(td: timedelta) -> float:
    return td / MIN


def hm(t) -> str:
    return "--:--" if t is None else f"{t:%H:%M}"


def jour_txt(j: date) -> str:
    return f"{JOURS_FR[j.weekday()]} {j:%d/%m}"


# =============================================================================
# 4. MESSAGES ET AGENT DE BASE
# =============================================================================

@dataclass
class Message:
    performatif: str
    emetteur: str
    destinataire: str
    sujet: str
    contenu: dict = field(default_factory=dict)
    conversation: str = ""
    heure: Optional[datetime] = None
    resume: str = ""

    def reponse(self, performatif: str, contenu: Optional[dict] = None, resume: str = "", sujet: str = "") -> "Message":
        return Message(performatif, self.destinataire, self.emetteur, sujet or self.sujet, contenu or {},
                       self.conversation, self.heure, resume)


class AgentSMA(mesa.Agent):
    """Agent Mesa qui communique par messages : `sur_<sujet>` traite un message reçu."""
    role = "agent"

    def __init__(self, model: "BlocOperatoire", nom: str):
        super().__init__(model)
        self.nom = nom
        model.annuaire[nom] = self

    @property
    def p(self) -> ParametresSMA:
        return self.model.parametres

    @property
    def maintenant(self) -> datetime:
        return self.model.maintenant

    def recevoir(self, msg: Message) -> list[Message]:
        gestionnaire = getattr(self, f"sur_{msg.sujet}", None)
        if gestionnaire is None:
            return [msg.reponse("REFUSE", {"motif": "sujet inconnu"}, "sujet inconnu")]
        rep = gestionnaire(msg)
        return [] if rep is None else rep if isinstance(rep, list) else [rep]

    def envoyer(self, destinataire, performatif, sujet, contenu, conversation="", resume="") -> list[Message]:
        return self.model.acheminer(Message(performatif, self.nom, destinataire, sujet, contenu, conversation,
                                            self.maintenant, resume))

    def diffuser(self, classe, performatif, sujet, contenu, conversation="", resume="") -> list[Message]:
        reponses = []
        for a in sorted(self.model.agents_by_type.get(classe, []), key=lambda a: a.nom):
            reponses += self.envoyer(a.nom, performatif, sujet, contenu, conversation, resume)
        return reponses

    def annoncer(self, texte: str, niveau: int = 1):
        self.model.annoncer(texte, niveau)

    def step(self):
        pass


# =============================================================================
# 5. AGENTS
# =============================================================================

# ---------------------------------------------------------------- Triage
class AgentTriage(AgentSMA):
    role = "triage"

    def __init__(self, model, specialites: dict[int, str], garde: Optional[int]):
        super().__init__(model, "triage")
        self.specialites, self.garde = specialites, garde

    def sur_arrivee_urgence(self, msg: Message):
        evt: ArriveeUrgence = msg.contenu["evenement"]
        p = evt.patient
        # gravité donnée à l'arrivée ; à défaut : « urgente » pour un patient urgent / priorité 4
        nom = evt.gravite or ("urgente" if p.urgence or p.priorite >= 4 else "differable")
        if nom not in GRAVITES:
            raise ValueError(f"gravité inconnue : {nom!r} (attendu : {', '.join(GRAVITES)})")
        g = GRAVITES[nom]
        spe = p.specialite or self.specialites.get(p.chirurgien_id, "")
        competents = sorted({p.chirurgien_id} | {c for c, s in self.specialites.items() if s and s == spe})
        if self.garde is not None and self.garde not in competents and nom != "differable":
            competents.append(self.garde)
        lim = evt.heure + g.delai_max_min * MIN
        self.annoncer(f"  Triage : gravité {g.nom} -> incision avant {hm(lim) if lim.date() == evt.heure.date() else jour_txt(lim.date()) + ' ' + hm(lim)} ; "
                      f"chirurgiens compétents ({spe}) : {', '.join(self.model.nom_chir(c) for c in competents)}")
        return self.envoyer("regulation", "REQUEST", "inserer_urgence",
                            {"patient": p, "arrivee": evt.heure, "gravite": g, "chirurgiens": competents},
                            msg.conversation, f"P{p.id} {g.nom}")


# ---------------------------------------------------------------- Logistique
class AgentLogistique(AgentSMA):
    role = "logistique"

    def __init__(self, model, batiment: Batiment):
        super().__init__(model, "logistique")
        self.batiment = batiment
        self.pannes: dict[str, tuple[datetime, datetime]] = {}
        self._echeances: dict[str, Any] = {}

    def fenetres(self, origine: str):
        route = self.batiment.route(origine)
        if route is None:
            return []
        candidats = [a for a in self.batiment.ascenseurs if a.monte_lit and set(route) <= set(a.etages)]
        if not candidats:
            return [(datetime.min, datetime.max)]
        bloque = (datetime.min, datetime.max)
        for a in candidats:
            if a.id not in self.pannes:
                return []
            d, f = self.pannes[a.id]
            bloque = (max(bloque[0], d), min(bloque[1], f))
            if bloque[0] >= bloque[1]:
                return []
        return [bloque]

    def toutes_fenetres(self) -> dict:
        return {o: self.fenetres(o) for o in ("chambre", "urgences", "ambulatoire")}

    def monte_lit_disponible(self) -> bool:
        f = self.fenetres("chambre")
        return not f or not (f[0][0] <= self.maintenant < f[0][1])

    def sur_fenetres_transfert(self, msg: Message):
        f = self.toutes_fenetres()
        return msg.reponse("INFORM", {"fenetres": f}, "aucune restriction" if not f["chambre"] else
                           f"monte-lit indisponible jusqu'à {hm(f['chambre'][0][1])}")

    def sur_panne(self, msg: Message):
        evt = msg.contenu["evenement"]
        if isinstance(evt, FinPanne):
            return self._reparation(evt.ascenseur, "réparé", msg.conversation)
        debut = self.pannes.get(evt.ascenseur, (evt.heure, None))[0]
        fin = evt.fin_estimee or evt.heure + timedelta(hours=4)
        self.pannes[evt.ascenseur] = (debut, fin)
        # comportement proactif : à l'heure estimée, la logistique constate elle-même la remise en service
        if evt.ascenseur in self._echeances:
            self._echeances.pop(evt.ascenseur).cancel()
        self._echeances[evt.ascenseur] = self.model.planifier_action(
            fin, functools.partial(self._echeance, evt.ascenseur, msg.conversation))
        f = self.toutes_fenetres()
        texte = f"{evt.ascenseur} en panne jusqu'à {hm(fin)} (estimation)"
        if not f["chambre"] and not f["urgences"]:
            self.annoncer(f"  Logistique : {texte}, mais un autre monte-lit assure les transferts -> sans effet")
            return None
        self.annoncer(f"  Logistique : {texte}")
        return self.envoyer("regulation", "INFORM", "transferts_bloques", {"fenetres": f}, msg.conversation, texte)

    def _echeance(self, ascenseur: str, conversation: str):
        if ascenseur in self.pannes:
            self._echeances.pop(ascenseur, None)
            self.model.annoncer(f"\n[{jour_txt(self.maintenant.date())} {hm(self.maintenant)}] {conversation} — "
                                f"la logistique constate la remise en service de {ascenseur} (heure estimée atteinte)")
            self._reparation(ascenseur, "remis en service", conversation)

    def _reparation(self, ascenseur: str, mot: str, conversation: str):
        self.pannes.pop(ascenseur, None)
        if ascenseur in self._echeances:
            self._echeances.pop(ascenseur).cancel()
        self.annoncer(f"  Logistique : {ascenseur} {mot}")
        return self.envoyer("regulation", "INFORM", "transferts_retablis", {"fenetres": self.toutes_fenetres()},
                            conversation, f"{ascenseur} {mot}")


# ---------------------------------------------------------------- Hébergement
class AgentHebergement(AgentSMA):
    role = "hebergement"

    def __init__(self, model, hebergement):
        super().__init__(model, "hebergement")
        self.h = hebergement
        self.sejours: dict[int, tuple[Patient, date]] = {}

    def occupation(self, sejours=None):
        lits, places = {}, {}
        for p, j in (self.sejours if sejours is None else sejours).values():
            cible = places if p.ambulatoire else lits
            for d in jours_occupation(p, j):
                cible[d] = cible.get(d, 0) + 1
        return lits, places

    def sur_evaluer_sejours(self, msg: Message):
        apres = dict(self.sejours)
        for pid in msg.contenu.get("retraits", []):
            apres.pop(pid, None)
        urgents = False
        for p, j in msg.contenu.get("ajouts", []):
            apres[p.id] = (p, j)
            urgents |= p.urgence
        l0, p0 = self.occupation()
        l1, p1 = self.occupation(apres)
        cout, motifs = 0.0, []
        for d in sorted(l1):
            avant, ap = l0.get(d, 0), l1[d]
            if ap <= avant or ap <= self.h.cap_lits:
                continue
            en_plus = ap - max(avant, self.h.cap_lits)
            if not urgents:
                return msg.reponse("REFUSE", {"motif": f"plus de lit le {d:%d/%m}"}, f"plus de lit le {d:%d/%m}")
            r = min(en_plus, max(0, self.h.lits_disponibles_par_jour - max(avant, self.h.cap_lits)))
            cout += r * self.p.c_lit_reserve + (en_plus - r) * self.p.c_lit_depassement
            motifs.append(f"{d:%d/%m}: " + ", ".join(x for x in (f"{r} lit(s) de réserve" if r else "",
                                                               f"{en_plus - r} lit(s) hors capacité" if en_plus > r else "") if x))
        for d in sorted(p1):
            if p1[d] > max(p0.get(d, 0), self.h.cap_places):
                if not urgents:
                    return msg.reponse("REFUSE", {"motif": f"plus de place ambulatoire le {d:%d/%m}"}, "places pleines")
                cout += self.p.c_lit_reserve
                motifs.append(f"{d:%d/%m}: place ambulatoire en surnombre")
        return msg.reponse("AGREE", {"cout": cout, "motif": "; ".join(motifs)}, "; ".join(motifs) or "capacité OK")

    def sur_maj_sejours(self, msg: Message):
        for pid in msg.contenu.get("retraits", []):
            self.sejours.pop(pid, None)
        for p, j in msg.contenu.get("ajouts", []):
            self.sejours[p.id] = (p, j)


# ---------------------------------------------------------------- Chirurgien
class AgentChirurgien(AgentSMA):
    role = "chirurgien"

    def __init__(self, model, chir_id: int, nom_affiche: str, jours_presence: set[date]):
        super().__init__(model, f"chir_{chir_id}")
        self.chir_id, self.nom_affiche, self.jours_presence = chir_id, nom_affiche, jours_presence
        self.agenda: dict[int, tuple[datetime, datetime, int]] = {}
        self.au_bloc: Optional[int] = None

    def sur_verifier_agenda(self, msg: Message):
        proposes = msg.contenu["intervalles"]
        ignores = {pid for pid, *_ in proposes} | set(msg.contenu.get("retraits", []))
        tous = [(d, f, s, pid) for pid, (d, f, s) in self.agenda.items() if pid not in ignores] + \
               [(d, f, s, pid) for pid, d, f, s in proposes]
        for pid, d, f, s in proposes:
            if self.model.chirurgien_absent(self.chir_id, d, f):
                motif = f"absent le {jour_txt(d.date())}"
                return msg.reponse("REFUSE", {"motif": motif}, motif)
            for d2, f2, s2, pid2 in tous:
                if pid2 != pid and chevauche(d, f, d2, f2):
                    motif = f"déjà au bloc (salle {s2}) de {hm(d2)} à {hm(f2)}"
                    return msg.reponse("REFUSE", {"motif": motif}, motif)
        astreinte = any(d.date() not in self.jours_presence for _, d, _, _ in proposes)
        return msg.reponse("AGREE", {"cout": self.p.c_astreinte if astreinte else 0.0},
                           "rappel d'astreinte" if astreinte else "disponible")

    def sur_instantane_agenda(self, msg: Message):
        """Instantané de l'agenda, transmis aux Salles dans les appels d'offres."""
        return msg.reponse("INFORM", {"chirurgien": self.chir_id,
                                      "occupe": [(d, f, pid) for pid, (d, f, _) in self.agenda.items()
                                                 if f > msg.contenu.get("apres", datetime.min)]},
                           f"{len(self.agenda)} intervention(s) à l'agenda")

    def sur_maj_agenda(self, msg: Message):
        for pid in msg.contenu.get("retraits", []):
            self.agenda.pop(pid, None)
        for pid, d, f, s in msg.contenu.get("intervalles", []):
            self.agenda[pid] = (d, f, s)

    def step(self):
        t = self.maintenant
        self.au_bloc = next((pid for pid, (d, f, _) in self.agenda.items() if d <= t < f), None)


# ---------------------------------------------------------------- Salle
class AgentSalle(AgentSMA):
    """Possède l'ordonnancement de ses créneaux (vacations + plages d'urgence)."""
    role = "salle"

    def __init__(self, model, salle_id: int, nom_affiche: str, fenetres: list[Fenetre]):
        super().__init__(model, f"salle_{salle_id}")
        self.salle_id, self.nom_affiche = salle_id, nom_affiche
        self.creneaux: dict[int, Fenetre] = {f.id: f for f in fenetres}
        self.interventions: dict[int, Intervention] = {}
        self.en_cours: Optional[int] = None
        self.n_evaluations = 0                     # plans chiffrés (comparaison glouton / métaheuristiques)

    # ---------------- outils
    def du_creneau(self, fid: int) -> list[Intervention]:
        return sorted((i for i in self.interventions.values() if i.fenetre_id == fid), key=lambda i: i.debut)

    def du_jour(self, jour: date) -> list[Intervention]:
        return sorted((i for i in self.interventions.values() if i.debut.date() == jour), key=lambda i: i.debut)

    def _etat_creneau(self, fen: Fenetre, maintenant: datetime):
        items = self.du_creneau(fen.id)
        commencees = [i for i in items if i.debut < maintenant]
        libres = [i for i in items if i.debut >= maintenant]
        t0 = max([fen.debut, maintenant] + [i.fin for i in commencees])
        return libres, t0

    def _occupations(self, agendas: Optional[dict], fen: Fenetre, ignorer=()) -> dict[int, list]:
        """Intervalles où chaque chirurgien est pris AILLEURS que dans ce créneau (instantané de la régulation).
        `ignorer` : patients en cours de déplacement (leur ancien horaire ne compte pas)."""
        if not agendas:
            return {}
        ici = {i.pid for i in self.du_creneau(fen.id)} | set(ignorer)
        return {cid: [(d, f) for d, f, pid in occ if pid not in ici] for cid, occ in agendas.items()}

    def _sequencer(self, items, minimums, t0, fenetres, en_liste: bool, occ: Optional[dict] = None):
        """Placement à la suite depuis t0 ; en_liste=True : au plus tôt réalisable d'abord (ordre initial
        en cas d'égalité) -> les ambulatoires passent devant les hospitalisés bloqués par l'ascenseur.
        `occ` : agendas des chirurgiens -> on ne place pas un patient quand son chirurgien est ailleurs."""
        t, restant, res = t0, list(items), []
        occ = occ or {}
        while restant:
            choix = None
            for it in (restant if en_liste else restant[:1]):
                s = premier_debut_possible(max(t, minimums[it.pid]), it.duree, fenetres.get(it.origine, []),
                                           self.p.transfert_min, occ.get(it.chirurgien_id, ()))
                if choix is None or (s, it.debut) < choix[0]:
                    choix = ((s, it.debut), it, s)
            _, it, s = choix
            restant.remove(it)
            res.append((it, s))
            t = s + it.duree
        return res

    def _evaluer(self, fen: Fenetre, placement, retraits, fenetres, ctx: dict) -> Plan:
        self.n_evaluations += 1
        p, cout, det = self.p, 0.0, {}

        def ajoute(cle, v):
            nonlocal cout
            if v:
                det[cle] = det.get(cle, 0.0) + v
                cout += v

        valide, debut_urg, hors_delai, retenus = True, None, False, []
        nouveaux = {it.pid for it in ctx.get("ajouts", [])}
        for it, s in placement:
            fin = s + it.duree
            if fin > fen.fin or s < fen.debut:
                valide = False                       # on reste dans les heures du planning
            if it.pid == ctx.get("pid_nouveau"):
                debut_urg = s
                ajoute("attente_urgence", minutes(s - ctx["arrivee"]) * ctx["poids_attente"])
                hors_delai = s > ctx["limite"]
            elif it.urgence and ctx.get("reference_initiale"):
                ajoute("attente_urgence", minutes(s - it.debut_initial) * 10.0)   # avancer une urgence = gain
            elif it.pid not in nouveaux:
                d = minutes(s - (it.debut_initial if ctx.get("reference_initiale") else it.debut))
                ajoute("decalage", max(0.0, d) * it.patient.priorite * p.c_decalage_min)
                ajoute("avance", max(0.0, -d) * it.patient.priorite * p.c_avance_min)
            if not it.patient.ambulatoire:
                r = retention_sspi(fin, fenetres.get("chambre", []), p)
                if r > 0:
                    retenus.append(it.pid)
                    ajoute("retention_sspi", r * p.c_retention_sspi_min)
        for it in retraits:
            ajoute("deprogrammation", p.c_deprogrammation * it.patient.priorite)
        for cle, v in ctx.get("couts_fixes", {}).items():
            ajoute(cle, v)
        if not valide:
            cout += INFAISABLE
        plan = Plan(self.salle_id, fen.id, fen.jour, {it.pid: s for it, s in placement},
                    ajouts=[a.copie(debut=s, debut_initial=s if a.urgence else a.debut_initial)
                            for a in ctx.get("ajouts", []) for it, s in placement if it.pid == a.pid],
                    retraits=[it.pid for it in retraits], cout=cout, detail=det, hors_delai=hors_delai,
                    debut_urgence=debut_urg, retenus_sspi=retenus)
        plan.resume = self._decrire(plan, placement, retraits, fen)
        return plan

    def _decrire(self, plan: Plan, placement, retraits, fen: Fenetre) -> str:
        morceaux, nouveaux = [], {a.pid: a for a in plan.ajouts}
        for it, s in placement:
            if it.pid in nouveaux:
                a = nouveaux[it.pid]
                qui = self.model.nom_chir(a.chirurgien_id)
                if a.urgence:
                    morceaux.append(f"urgence P{it.pid} {hm(s)}-{hm(s + it.duree)} ({qui})")
                else:
                    chg = f", repris par {qui}" if a.chirurgien_id != a.chirurgien_initial else ""
                    morceaux.append(f"P{it.pid} placé {hm(s)}{chg}")
            elif s != it.debut:
                d = int(minutes(s - it.debut))
                morceaux.append(f"P{it.pid} {'+' if d > 0 else ''}{d} min")
        morceaux += [f"P{it.pid} {'(urgence ' + it.gravite + ') ' if it.urgence else ''}reporté" for it in retraits]
        cadre = "plage urgences" if fen.urgence else f"vacation {self.model.nom_chir(fen.chirurgien_id)}"
        return (f"{self.nom_affiche} {jour_txt(fen.jour)} ({cadre} {hm(fen.debut)}-{hm(fen.fin)}) : "
                + (", ".join(morceaux) or "aucun changement"))

    def _avec_deprogrammations(self, fen, items, construire, fenetres, ctx) -> list[Plan]:
        """Variante sans report, puis jusqu'à k reports gloutons (k = ctx["max_deprog"], None = sans plafond)."""
        plans, courant, retires = [], list(items), []
        base = self._evaluer(fen, construire(courant), retires, fenetres, ctx)
        if base.cout < INFAISABLE:
            plans.append(base)
        meilleur_cout = base.cout
        proteges = {a.pid for a in ctx.get("ajouts", [])}
        # une urgence déjà insérée n'est déprogrammée que (a) en cas de panne (ctx « urgences_deplacables ») où elle
        # ne peut physiquement plus monter au bloc, ou (b) au niveau 2 de l'escalade, par une urgence STRICTEMENT
        # plus grave (ctx « rang_nouveau ») ; elle repasse alors par l'appel d'offres urgence avec son propre délai.
        urg_ok = ctx.get("urgences_deplacables", False)
        rang = ctx.get("rang_nouveau", 0)
        k = ctx.get("max_deprog", self.p.max_deprogrammations)
        for _ in range(len(courant) if k is None else k):
            meilleur = None
            for it in courant:
                evincable = urg_ok or (it.gravite in GRAVITES and GRAVITES[it.gravite].rang < rang)
                if (it.urgence and not evincable) or it.pid in proteges:   # un patient programmé « urgent » reste déprogrammable
                    continue
                essai = [x for x in courant if x is not it]
                plan = self._evaluer(fen, construire(essai), retires + [it], fenetres, ctx)
                if meilleur is None or plan.cout < meilleur[0].cout:
                    meilleur = (plan, it)
            if meilleur is None:
                break
            plan, it = meilleur
            courant.remove(it)
            retires.append(it)
            if plan.cout < INFAISABLE and plan.cout < meilleur_cout:
                plans.append(plan)
                meilleur_cout = plan.cout
        return plans

    def _retirables(self, items, ctx) -> set[int]:
        """Patients que ce plan a le droit de reporter (mêmes règles que _avec_deprogrammations)."""
        urg_ok, rang = ctx.get("urgences_deplacables", False), ctx.get("rang_nouveau", 0)
        proteges = {a.pid for a in ctx.get("ajouts", [])}
        return {it.pid for it in items if it.pid not in proteges and
                (not it.urgence or urg_ok or (it.gravite in GRAVITES and GRAVITES[it.gravite].rang < rang))}

    def _ameliorer(self, fen, items, construire, fenetres, ctx, plans_fen: list[Plan], appel: str,
                   evaluations_glouton: int = 0) -> list[Plan]:
        """CAS B : optimisation locale du créneau (ordre de passage + reports) par une métaheuristique courte,
        en partant du meilleur plan glouton. Renvoie le plan amélioré, ou rien (on garde alors le glouton)."""
        meth = self.p.methode_locale
        if not meth or meth == "glouton" or len(items) < 2:
            return []
        from optimisation_sma import ProblemeLocalSalle, optimiser_localement
        depart = min(plans_fen, key=lambda pl: (pl.hors_delai, pl.cout)) if plans_fen else None
        pb = ProblemeLocalSalle(self, fen, items, construire, fenetres, ctx, self._retirables(items, ctx),
                                ctx.get("max_deprog", self.p.max_deprogrammations), depart)
        pb.evaluations_glouton, pb.appel = evaluations_glouton, appel
        pb.cout_glouton = depart.cout + (1e7 if depart.hors_delai else 0.0) if depart else float("inf")
        res = optimiser_localement(self, pb)
        plan = pb.plan(res.individu)
        ref = (depart.hors_delai, depart.cout) if depart else (True, INFAISABLE)
        ameliore = pb.valide(res.individu) and plan.cout < INFAISABLE and (plan.hors_delai, plan.cout + 1e-6) < ref
        self.model.traces_locales.append({"heure": self.maintenant, "salle": self.salle_id, "appel": appel,
                                          "methode": meth, "cout_glouton": depart.cout if depart else None,
                                          "cout_local": plan.cout if plan.cout < INFAISABLE else None,
                                          "ameliore": ameliore, "evaluations": res.evaluations, "temps_s": res.temps_s,
                                          "evaluations_glouton": evaluations_glouton})
        if self.p.capturer_problemes:
            self.model.problemes_locaux.append(pb)
        if ameliore:
            plan.detail["optimisation_locale"] = (depart.cout - plan.cout) if depart else 0.0
            return [plan]
        return []

    def sur_etat_programme(self, msg: Message):
        """Pour l'agent Optimisation : interventions et créneaux de la salle."""
        return msg.reponse("INFORM", {"interventions": list(self.interventions.values()),
                                      "creneaux": {(self.salle_id, f.id): f for f in self.creneaux.values()
                                                   if not self.model.fenetre_fermee(f)}},
                           f"{len(self.interventions)} intervention(s)")

    def _top(self, plans: list[Plan]) -> list[Plan]:
        vus, res = set(), []
        for pl in sorted(plans, key=lambda x: (x.hors_delai, x.cout)):
            if pl.signature() not in vus:
                vus.add(pl.signature())
                res.append(pl)
        return res[:self.p.propositions_par_salle]

    # ---------------- CFP : insertion d'une urgence
    def sur_cfp_urgence(self, msg: Message):
        c = msg.contenu
        maintenant, fenetres = c["maintenant"], c["fenetres"]
        plans = []
        for fen in self.creneaux.values():
            if fen.jour not in c["jours"] or fen.fin <= c["t_min"] or self.model.fenetre_fermee(fen):
                continue
            # vacation : opérée par SON chirurgien s'il est compétent ; plage d'urgence : tout chirurgien compétent
            chirs = c["chirurgiens"] if fen.urgence else [fen.chirurgien_id] if fen.chirurgien_id in c["chirurgiens"] else []
            chirs = [cid for cid in chirs if not self.model.chirurgien_absent(cid, fen.debut, fen.fin)]
            occ = self._occupations(c.get("agendas"), fen)
            for cid in chirs:
                patient = replace(c["patient"], chirurgien_id=cid)
                duree = timedelta(minutes=patient.duree_bloc)
                # au plus tôt : brancardage possible ET chirurgien libre (instantané de son agenda)
                t_min = premier_debut_possible(max(c["t_min"], fen.debut), duree, fenetres.get("urgences", []),
                                               self.p.transfert_min, occ.get(cid, ()))
                if t_min + duree > fen.fin:
                    continue
                libres, t0 = self._etat_creneau(fen, maintenant)
                nouvelle = Intervention(patient, self.salle_id, t_min, fen.id, urgence=True,
                                        chirurgien_initial=c["patient"].chirurgien_id, gravite=c.get("gravite"))
                ctx = dict(c["ctx"], pid_nouveau=patient.id, ajouts=[nouvelle])
                minimums = {i.pid: i.debut for i in libres} | {patient.id: t_min}
                construire = lambda its, m=minimums, t=t0, o=occ: self._sequencer(its, m, t, fenetres, False, o)
                plans_fc, n0 = [], self.n_evaluations
                for pos in range(len(libres) + 1):             # glouton : chaque position d'insertion
                    ordre = libres[:pos] + [nouvelle] + libres[pos:]
                    plans_fc += self._avec_deprogrammations(fen, ordre, construire, fenetres, ctx)
                # cas B : la salle améliore localement son meilleur plan glouton
                plans += plans_fc + self._ameliorer(fen, libres + [nouvelle], construire, fenetres, ctx, plans_fc,
                                                    "urgence", self.n_evaluations - n0)
        top = self._top(plans)
        if not top:
            return msg.reponse("REFUSE", {"motif": "aucun créneau"}, "aucune insertion possible")
        return msg.reponse("PROPOSE", {"plans": top}, f"{len(top)} proposition(s), meilleure : coût {top[0].cout:,.0f}")

    # ---------------- CFP : adaptation à une panne
    def sur_cfp_panne(self, msg: Message):
        c = msg.contenu
        maintenant, fenetres = c["maintenant"], c["fenetres"]
        jours = {d.date() for f in fenetres.values() for a, b in f for d in (a, b) if d not in (datetime.min, datetime.max)}
        plans, non_resolus = [], []
        for fen in self.creneaux.values():
            if fen.jour not in jours or fen.fin <= maintenant or self.model.fenetre_fermee(fen):
                continue
            libres, t0 = self._etat_creneau(fen, maintenant)
            impactees = [i for i in libres if premier_transfert_possible(
                i.debut, fenetres.get(i.origine, []), self.p.transfert_min) != i.debut]
            sspi = [i.pid for i in self.du_creneau(fen.id) if not i.patient.ambulatoire
                    and retention_sspi(i.fin, fenetres.get("chambre", []), self.p) > 0]
            if not impactees:
                if sspi:
                    plans.append(Plan(self.salle_id, fen.id, fen.jour, {}, retenus_sspi=sspi))
                continue
            minimums = {i.pid: max(i.debut - self.p.avance_max_min * MIN, fen.debut, maintenant) for i in libres}
            ctx = {"ajouts": [], "urgences_deplacables": True}
            occ = self._occupations(c.get("agendas"), fen)
            avant, n0 = len(plans), self.n_evaluations
            for en_liste in (True, False):         # réordonner (ambulatoires d'abord) OU simplement décaler
                construire = lambda its, m=minimums, t=t0, l=en_liste, o=occ: self._sequencer(its, m, t, fenetres, l, o)
                plans += self._avec_deprogrammations(fen, libres, construire, fenetres, ctx)
            # cas B : optimisation locale de l'ordre (construire respecte l'ordre proposé : en_liste=False)
            plans += self._ameliorer(fen, libres, construire, fenetres, ctx, plans[avant:], "panne",
                                     self.n_evaluations - n0)
            if len(plans) == avant:                # impacté mais aucune solution dans ce créneau : on le signale
                non_resolus.append((fen.id, [i.pid for i in impactees]))
            elif sspi:
                for pl in plans[avant:]:
                    pl.retenus_sspi = sorted(set(pl.retenus_sspi) | set(sspi))
        if not plans and not non_resolus:
            return msg.reponse("INFORM", {"plans": []}, "salle non impactée")
        top = []
        for fid in sorted({pl.fenetre_id for pl in plans}):        # meilleures propositions PAR créneau
            top += self._top([pl for pl in plans if pl.fenetre_id == fid])
        return msg.reponse("PROPOSE", {"plans": top, "non_resolus": non_resolus},
                           f"{len(top)} proposition(s)" + (f", {len(non_resolus)} créneau(x) sans solution"
                                                            if non_resolus else ""))

    # ---------------- CFP : rattrapage après la panne
    def sur_cfp_compacter(self, msg: Message):
        c = msg.contenu
        maintenant, fenetres = c["maintenant"], c["fenetres"]
        pret = maintenant + self.p.preparation_rattrapage_min * MIN
        plans = []
        for fen in self.creneaux.values():
            if fen.jour != maintenant.date() or fen.fin <= maintenant or self.model.fenetre_fermee(fen):
                continue
            libres, t0 = self._etat_creneau(fen, maintenant)
            if not any(i.debut > i.debut_initial or i.urgence for i in libres):
                continue
            minimums = {i.pid: min(max(pret, fen.debut) if i.urgence else
                                   max(pret, fen.debut, i.debut_initial - self.p.avance_max_min * MIN), i.debut)
                        for i in libres}
            ctx = {"reference_initiale": True, "ajouts": []}
            actuel = self._evaluer(fen, [(i, i.debut) for i in libres], [], fenetres, ctx)
            plan = self._evaluer(fen, self._sequencer(libres, minimums, t0, fenetres, True,
                                                      self._occupations(c.get("agendas"), fen)), [], fenetres, ctx)
            plan.placements = {pid: s for pid, s in plan.placements.items() if s != self.interventions[pid].debut}
            if plan.placements and plan.cout < actuel.cout - 1e-6:
                plan.detail["gain"] = actuel.cout - plan.cout
                plans.append(plan)
        if not plans:
            return msg.reponse("INFORM", {"plans": []}, "rien à rattraper")
        return msg.reponse("PROPOSE", {"plans": plans}, f"{len(plans)} rattrapage(s)")

    # ---------------- CFP : replacer un patient (déprogrammé ou en liste d'attente)
    def sur_cfp_replacement(self, msg: Message):
        c = msg.contenu
        it0: Intervention = c["intervention"]
        apres, fenetres, competents = c["apres"], c["fenetres"], c["chirurgiens"]
        p0 = it0.patient
        plans = []
        for fen in self.creneaux.values():
            if fen.urgence or fen.chirurgien_id not in competents or fen.fin <= apres or fen.jour < apres.date():
                continue
            if self.model.fenetre_fermee(fen) or fen.jour in c.get("jours_exclus", ()):
                continue
            if p0.date_min is not None and fen.jour < p0.date_min:
                continue
            libres, t0 = self._etat_creneau(fen, max(apres, self.maintenant))
            patient = replace(p0, chirurgien_id=fen.chirurgien_id)
            nouvelle = it0.copie(patient=patient, salle_id=self.salle_id, fenetre_id=fen.id, debut=t0)
            jours = (fen.jour - c["jour_reference"]).days
            fixes = {"report": self.p.c_report_jour * p0.priorite * max(0, jours)}
            if fen.chirurgien_id != it0.chirurgien_initial:
                fixes["changement_chirurgien"] = self.p.c_changement_chirurgien
            futur = fen.jour > self.maintenant.date()
            charge = sum(i.patient.duree_bloc for i in self.du_creneau(fen.id))
            # option : prendre la place d'un patient strictement moins prioritaire (il sera replacé à son tour)
            candidats = [[]] + [[i] for i in libres if i.patient.priorite < p0.priorite and not i.urgence]
            for retires in candidats:
                restants = [i for i in libres if i not in retires]
                # créneau futur : on garde la marge de 10 % pour les aléas ; aujourd'hui : jusqu'à la fin du créneau
                if futur and charge - sum(i.patient.duree_bloc for i in retires) + p0.duree_bloc > fen.capacite_utile_min + 1e-9:
                    continue
                # jour futur : l'ordre de passage n'est pas figé, on re-séquence depuis le début du créneau ;
                # aujourd'hui : avance limitée (patient convoqué au plus 1 h plus tôt)
                minimums = {i.pid: fen.debut if futur else max(t0, i.debut - self.p.avance_max_min * MIN)
                            for i in restants} | {p0.id: max(t0, apres)}
                placement = self._sequencer(restants + [nouvelle], minimums, t0, fenetres, False,
                                            self._occupations(c.get("agendas"), fen, {p0.id}))
                plan = self._evaluer(fen, placement, retires, fenetres, {"ajouts": [nouvelle], "couts_fixes": fixes})
                if plan.cout < INFAISABLE:
                    plans.append(plan)
        top = sorted(plans, key=lambda x: x.cout)[:self.p.propositions_par_salle]
        if not top:
            return msg.reponse("REFUSE", {"motif": "pas de place"}, "pas de place")
        return msg.reponse("PROPOSE", {"plans": top}, f"{len(top)} proposition(s), meilleure : {top[0].resume}")

    # ---------------- décision
    def sur_accept_proposal(self, msg: Message):
        plan: Plan = msg.contenu["plan"]
        retirees = [self.interventions.pop(pid) for pid in plan.retraits]
        for it in plan.ajouts:
            self.interventions[it.pid] = it
        for pid, s in plan.placements.items():
            self.interventions[pid].debut = s
        par_chir: dict[int, dict] = {}
        for pid in plan.placements:
            it = self.interventions[pid]
            par_chir.setdefault(it.chirurgien_id, {"intervalles": [], "retraits": []})["intervalles"].append(
                (pid, it.debut, it.fin, self.salle_id))
        for it in retirees:
            par_chir.setdefault(it.chirurgien_id, {"intervalles": [], "retraits": []})["retraits"].append(it.pid)
        for cid, contenu in sorted(par_chir.items()):
            self.envoyer(f"chir_{cid}", "INFORM", "maj_agenda", contenu, msg.conversation, "agenda mis à jour")
        self.envoyer("hebergement", "INFORM", "maj_sejours",
                     {"ajouts": [(it.patient, it.debut.date()) for it in plan.ajouts],
                      "retraits": [it.pid for it in retirees]}, msg.conversation, "séjours mis à jour")
        return msg.reponse("INFORM", {"retirees": retirees}, "plan appliqué", sujet="plan_applique")

    def sur_reject_proposal(self, msg: Message):
        return None

    def sur_lister_decales(self, msg: Message):
        """Patients du jour, pas encore commencés, nettement plus tard que prévu (candidats à un rattrapage)."""
        t, seuil = msg.contenu["apres"], msg.contenu["seuil_min"] * MIN
        its = [i for i in self.interventions.values() if not i.urgence and i.debut.date() == t.date()
               and i.debut > t and i.debut - i.debut_initial >= seuil]
        return msg.reponse("INFORM", {"interventions": its}, f"{len(its)} patient(s) décalé(s)")

    def step(self):
        t = self.maintenant
        self.en_cours = next((i.pid for i in self.interventions.values() if i.debut <= t < i.fin), None)


# ---------------------------------------------------------------- Garde
class _SallesAvecGarde(dict):
    """Salles du programme ; `salles[ID_SALLE_GARDE]` renvoie la salle de garde (pour l'interface, qui lit
    `modele.salles[decision["salle"]]`). Elle n'apparaît PAS quand on parcourt les salles du programme."""

    def __init__(self, salles, garde):
        super().__init__(salles)
        self.garde = garde

    def __missing__(self, cle):
        if cle == ID_SALLE_GARDE:
            return self.garde
        raise KeyError(cle)


@dataclass
class EquipeGarde:
    """Pseudo-chirurgien de la garde : `modele.chirurgiens[ID_EQUIPE_GARDE]` (mêmes attributs utiles
    qu'un AgentChirurgien) ; non parcouru avec les vrais chirurgiens."""
    garde: "AgentGarde"
    chir_id: int = ID_EQUIPE_GARDE
    nom_affiche: str = "Équipe de garde"
    nom: str = "chir_garde"

    @property
    def agenda(self) -> dict:
        return {i.pid: (i.debut, i.fin, ID_SALLE_GARDE) for i in self.garde.interventions.values()}

    @property
    def au_bloc(self):
        return self.garde.en_cours

    @property
    def jours_presence(self) -> set:
        return set()


class _ChirurgiensAvecGarde(dict):
    def __init__(self, chirurgiens, garde):
        super().__init__(chirurgiens)
        self.equipe_garde = EquipeGarde(garde)

    def __missing__(self, cle):
        if cle == ID_EQUIPE_GARDE:
            return self.equipe_garde
        raise KeyError(cle)


class AgentGarde(AgentSMA):
    """Planning de garde : une salle et une équipe hors des heures du programme (soirs, nuits, jours sans
    programme). Prend toute urgence que le programme ne peut pas absorber — il ne refuse jamais — puis
    prévient le système (INFORM à la régulation, mise à jour de l'hébergement)."""
    role = "garde"

    def __init__(self, model, jours_programme: set[date]):
        super().__init__(model, "garde")
        self.nom_affiche = "Salle de garde"
        self.salle_id = ID_SALLE_GARDE
        self.creneaux: dict[int, Fenetre] = {}       # pas de créneaux du programme
        self.jours_programme = jours_programme
        self.interventions: dict[int, Intervention] = {}
        self.en_cours: Optional[int] = None

    def en_garde(self, t: datetime, gravite: Optional[str] = None) -> bool:
        if self.p.garde_permanente or gravite in self.p.garde_immediate or t.date() not in self.jours_programme:
            return True
        return t.time() >= self.p.garde_soir or t.time() < self.p.garde_matin

    def premier_creneau(self, t_min: datetime, duree: timedelta, fenetres, gravite: Optional[str] = None) -> datetime:
        """Au plus tôt : heures de garde (ou tout de suite pour une gravité `garde_immediate`), brancardage
        possible, salle de garde libre."""
        occupe = [(i.debut, i.fin) for i in self.interventions.values()]
        s = t_min
        while True:
            debut = s if self.en_garde(s, gravite) else datetime.combine(s.date(), self.p.garde_soir)
            debut = premier_debut_possible(debut, duree, fenetres, self.p.transfert_min, occupe)
            if debut == s:
                return s
            s = debut

    def du_jour(self, jour: date) -> list[Intervention]:
        return sorted((i for i in self.interventions.values() if i.debut.date() == jour), key=lambda i: i.debut)

    def du_creneau(self, fid: int) -> list[Intervention]:
        return sorted(self.interventions.values(), key=lambda i: i.debut) if fid == ID_FENETRE_GARDE else []

    def sur_etat_programme(self, msg: Message):
        return msg.reponse("INFORM", {"interventions": list(self.interventions.values()), "creneaux": {}},
                           f"{len(self.interventions)} urgence(s) en garde")

    def sur_cfp_garde(self, msg: Message):
        c = msg.contenu
        patient = replace(c["patient"], chirurgien_id=ID_EQUIPE_GARDE)
        s = self.premier_creneau(c["t_min"], timedelta(minutes=patient.duree_bloc), c["fenetres"].get("urgences", []),
                                 c["gravite"])
        it = Intervention(patient, ID_SALLE_GARDE, s, ID_FENETRE_GARDE, urgence=True,
                          chirurgien_initial=c["patient"].chirurgien_id, gravite=c["gravite"])
        ctx = c["ctx"]
        attente = minutes(s - ctx["arrivee"])
        plan = Plan(ID_SALLE_GARDE, ID_FENETRE_GARDE, s.date(), {patient.id: s}, ajouts=[it],
                    cout=attente * ctx["poids_attente"], detail={"attente_urgence": attente * ctx["poids_attente"]},
                    hors_delai=s > ctx["limite"], debut_urgence=s,
                    resume=f"Salle de garde {jour_txt(s.date())} : urgence P{patient.id} {hm(s)}-{hm(it.fin)} (équipe de garde)")
        return msg.reponse("PROPOSE", {"plan": plan}, f"possible à {hm(s)} le {jour_txt(s.date())}")

    def sur_accept_garde(self, msg: Message):
        plan: Plan = msg.contenu["plan"]
        it = plan.ajouts[0]
        self.interventions[it.pid] = it
        self.envoyer("hebergement", "INFORM", "maj_sejours", {"ajouts": [(it.patient, it.debut.date())], "retraits": []},
                     msg.conversation, "séjour ajouté (garde)")
        # le système est prévenu : la régulation trace l'alerte, l'équipe de garde a le patient dans son planning
        self.envoyer("regulation", "INFORM", "urgence_confiee_garde",
                     {"patient": it.pid, "gravite": msg.contenu["gravite"], "debut": it.debut,
                      "arrivee": msg.contenu["arrivee"]}, msg.conversation,
                     f"P{it.pid} pris en charge par la garde à {hm(it.debut)}")
        return msg.reponse("INFORM", {"retirees": []}, "urgence inscrite au planning de garde", sujet="plan_applique")

    def step(self):
        t = self.maintenant
        self.en_cours = next((i.pid for i in self.interventions.values() if i.debut <= t < i.fin), None)


# ---------------------------------------------------------------- Régulation
class AgentRegulation(AgentSMA):
    role = "regulation"

    def __init__(self, model, specialites: dict[int, str]):
        super().__init__(model, "regulation")
        self.specialites = specialites
        self.liste_attente: list[tuple[Intervention, date]] = []
        self.decisions: list[dict] = []
        self.alertes: list[str] = []
        self.urgences_info: dict[int, tuple] = {}     # pid -> (patient, arrivée, gravité, chirurgiens compétents)
        self.chirurgiens_autorises: dict[int, list[int]] = {}   # pid -> chirurgiens acceptés à la consultation
        self._dernier_matin: Optional[date] = None

    def competents(self, it: Intervention) -> list[int]:
        """Chirurgiens pouvant opérer ce patient : son chirurgien et ceux de la même spécialité, ou seulement
        ceux acceptés à la consultation (confrère refusé) s'ils ont été enregistrés."""
        if it.pid in self.chirurgiens_autorises:
            return self.chirurgiens_autorises[it.pid]
        spe = it.patient.specialite or self.specialites.get(it.chirurgien_initial, "")
        return sorted({it.chirurgien_initial} | {c for c, s in self.specialites.items() if s and s == spe})

    def _fenetres(self, conv) -> dict:
        return self.envoyer("logistique", "REQUEST", "fenetres_transfert", {}, conv,
                            "état des monte-lits ?")[0].contenu["fenetres"]

    def _valider(self, plan: Plan, conv) -> tuple[bool, float, str]:
        salle = self.model.annuaire[f"salle_{plan.salle_id}"]
        nouveaux = {it.pid: it for it in plan.ajouts}
        par_chir: dict[int, list] = {}
        for pid, s in plan.placements.items():
            it = nouveaux.get(pid) or salle.interventions[pid]
            par_chir.setdefault(it.chirurgien_id, []).append((pid, s, s + it.duree, plan.salle_id))
        retraits: dict[int, list] = {}
        for pid in plan.retraits:
            retraits.setdefault(salle.interventions[pid].chirurgien_id, []).append(pid)
        extra, note = 0.0, ""
        for cid, inter in sorted(par_chir.items()):
            r = self.envoyer(f"chir_{cid}", "REQUEST", "verifier_agenda",
                             {"intervalles": inter, "retraits": retraits.get(cid, [])}, conv,
                             f"{len(inter)} créneau(x) à vérifier")[0]
            if r.performatif == "REFUSE":
                return False, 0.0, f"{self.model.nom_chir(cid)} : {r.contenu['motif']}"
            extra += r.contenu["cout"]
            if r.contenu["cout"]:
                note = f"{self.model.nom_chir(cid)} rappelé d'astreinte"
        changements = [(it.patient, it.debut.date()) for it in plan.ajouts]
        if changements or plan.retraits:
            r = self.envoyer("hebergement", "REQUEST", "evaluer_sejours",
                             {"ajouts": changements, "retraits": plan.retraits}, conv, "lits/places ?")[0]
            if r.performatif == "REFUSE":
                return False, 0.0, f"hébergement : {r.contenu['motif']}"
            extra += r.contenu["cout"]
            note = "; ".join(x for x in (note, r.contenu.get("motif", "")) if x)
        return True, extra, note

    def _agendas(self, conv) -> dict[int, list]:
        """Instantané des agendas des chirurgiens (par messages), transmis aux Salles dans les appels d'offres."""
        reps = self.diffuser(AgentChirurgien, "REQUEST", "instantane_agenda", {"apres": self.maintenant}, conv,
                             "agenda ?")
        return {r.contenu["chirurgien"]: r.contenu["occupe"] for r in reps if r.performatif == "INFORM"}

    def _choisir(self, propositions, conv, cle_tri):
        """Valide les plans auprès des ressources (chirurgiens, hébergement) et retient le meilleur selon
        `cle_tri` (tuple lexicographique ; son dernier terme, le coût, est complété par le coût des ressources)."""
        valides = []
        for agent, plan in sorted(propositions, key=lambda x: cle_tri(x[1])):
            ok, extra, motif = self._valider(plan, conv)
            if ok:
                valides.append((agent, plan, extra, motif))
            else:
                self.annoncer(f"    ✗ rejetée ({motif}) : {plan.resume}", 2)
        if not valides:
            return None
        return min(valides, key=lambda x: (*cle_tri(x[1])[:-1], x[1].cout + x[2]))

    def _appliquer(self, agent, plan, propositions, conv) -> list[Intervention]:
        for a in sorted({a for a, pl in propositions if pl is not plan}):
            self.envoyer(a, "REJECT_PROPOSAL", "reject_proposal", {}, conv, "")
        return self.envoyer(agent, "ACCEPT_PROPOSAL", "accept_proposal", {"plan": plan}, conv,
                            plan.resume)[0].contenu["retirees"]

    # ---------- urgence
    def sur_inserer_urgence(self, msg: Message):
        c = msg.contenu
        self.urgences_info[c["patient"].id] = (c["patient"], c["arrivee"], c["gravite"], c["chirurgiens"])
        ok, contenu, resume = self._inserer_urgence(c["patient"], c["arrivee"], c["gravite"], c["chirurgiens"],
                                                    msg.conversation)
        self.reoptimiser(msg.conversation, f"urgence P{c['patient'].id}")      # cas A, après la réaction immédiate
        return msg.reponse("AGREE", contenu, resume)        # jamais de refus

    def _reinserer_urgence(self, it: Intervention, conv):
        """Urgence déjà programmée mais déplacée (monte-lit en panne, ou évincée par une urgence plus grave) :
        nouvel appel d'offres avec le MÊME délai (compté depuis l'arrivée aux urgences)."""
        p, arrivee, g, chirurgiens = self.urgences_info[it.pid]
        self.annoncer(f"    ↳ urgence P{it.pid} ({g.nom}) ne peut plus être opérée à {hm(it.debut)} : nouvel appel d'offres")
        t_min = max(arrivee + g.preparation_min * MIN, self.maintenant + self.p.transfert_min * MIN)
        self._inserer_urgence(p, arrivee, g, chirurgiens, conv, t_min=t_min, reinsertion=True)

    def _appel_offres_urgence(self, p: Patient, g: Gravite, chirurgiens, t_min, jours, fenetres, ctx, conv, niveau):
        reponses = self.diffuser(AgentSalle, "CFP", "cfp_urgence",
                                 {"patient": p, "gravite": g.nom, "chirurgiens": chirurgiens, "t_min": t_min,
                                  "jours": jours, "maintenant": self.maintenant, "fenetres": fenetres,
                                  "agendas": self._agendas(conv), "ctx": ctx},
                                 conv, f"P{p.id} {p.duree_bloc} min, au plus tôt {hm(t_min)} — niveau {niveau} "
                                       f"({NIVEAUX_ESCALADE[niveau]})")
        return [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]]

    def _inserer_urgence(self, p: Patient, arrivee: datetime, g: Gravite, chirurgiens: list[int], conv,
                         t_min: Optional[datetime] = None, reinsertion: bool = False):
        """Échelle d'escalade : renvoie TOUJOURS un plan (programme ou planning de garde), jamais de refus."""
        fenetres = self._fenetres(conv)
        t_min = t_min or arrivee + g.preparation_min * MIN
        limite, acceptable = g.limite(arrivee), g.limite_acceptable(arrivee)
        futurs = sorted(j for j in self.model.jours_planning if j >= t_min.date())
        proches = {j for j in futurs if j <= acceptable.date()}
        ctx0 = {"arrivee": arrivee, "limite": limite, "poids_attente": g.poids_attente}
        leviers = {0: {"max_deprog": 0},                                     # décaler seulement
                   1: {"max_deprog": self.p.max_deprogrammations},           # + reporter (plafonné)
                   2: {"max_deprog": None, "rang_nouveau": g.rang}}          # + sans plafond, évincer moins grave
        choix = niveau = None
        props: list = []
        # niveaux 0 à 2 : le premier niveau qui donne un plan DANS LE DÉLAI est retenu
        for n in (0, 1, 2) if proches else ():
            props = self._appel_offres_urgence(p, g, chirurgiens, t_min, proches, fenetres, dict(ctx0, **leviers[n]),
                                               conv, n)
            choix = self._choisir([(a, pl) for a, pl in props if not pl.hors_delai], conv, lambda pl: (pl.cout,))
            if choix is not None:
                niveau = n
                break
        # niveau 3 : l'urgence attend (« quelques heures ») — plan hors délai mais avant délai + tolérance
        if choix is None and props:
            choix = self._choisir([(a, pl) for a, pl in props if pl.debut_urgence <= acceptable], conv,
                                  lambda pl: (pl.cout,))
            niveau = 3 if choix is not None else None
        # niveau 4 : planning de garde, sauf si le programme permet d'opérer plus tôt que la garde
        plan_garde = None
        if choix is None:
            niveau = 4
            props = self._appel_offres_urgence(p, g, chirurgiens, t_min, set(futurs), fenetres,
                                               dict(ctx0, **leviers[2]), conv, 4) if futurs else []
            plan_garde = self.envoyer("garde", "CFP", "cfp_garde",
                                      {"patient": p, "gravite": g.nom, "t_min": t_min, "fenetres": fenetres,
                                       "ctx": ctx0}, conv, f"P{p.id} : premier créneau de garde ?")[0].contenu["plan"]
            choix = self._choisir(props, conv, lambda pl: (pl.debut_urgence, pl.cout))
            if choix is not None and choix[1].debut_urgence < plan_garde.debut_urgence:
                plan_garde = None                         # le programme opère plus tôt que la garde
            else:
                choix = None

        if plan_garde is not None:
            return self._confier_garde(p, arrivee, g, plan_garde, props, conv, reinsertion)

        agent, plan, extra, note = choix
        retirees = self._appliquer(agent, plan, props, conv)
        nouvelle = plan.ajouts[0]
        attente = minutes(plan.debut_urgence - arrivee)
        self.annoncer(f"  ✔ {'Nouvelle décision' if reinsertion else 'Décision'} (niveau {niveau} : "
                      f"{NIVEAUX_ESCALADE[niveau]}) : P{p.id} opéré(e) par {self.model.nom_chir(nouvelle.chirurgien_id)} "
                      f"en {self.model.annuaire[agent].nom_affiche} à {hm(plan.debut_urgence)} le {jour_txt(plan.jour)} "
                      f"(attente {attente:.0f} min, {len(props)} propositions, coût {plan.cout + extra:,.0f})")
        self.annoncer(f"    {plan.resume}")
        self._noter_lits(p, note)
        if plan.hors_delai:
            self._alerte_delai(p, g, attente, f"{plan.resume} (coût {plan.cout + extra:,.0f})")
        self._enregistrer_urgence(p, g, niveau, plan.salle_id, nouvelle.chirurgien_id, plan.debut_urgence, attente,
                                  not plan.hors_delai, plan.cout + extra, plan.resume, len(props), reinsertion,
                                  garde=False, detail=plan.detail)
        self._replacer(retirees, conv)
        return True, {"plan": plan}, plan.resume

    def _confier_garde(self, p: Patient, arrivee: datetime, g: Gravite, plan: Plan, props, conv, reinsertion):
        """Niveau 4 : le programme n'a plus de place -> l'urgence est confiée au planning de garde."""
        for a in sorted({a for a, _ in props}):
            self.envoyer(a, "REJECT_PROPOSAL", "reject_proposal", {}, conv, "")
        r = self.envoyer("hebergement", "REQUEST", "evaluer_sejours",
                         {"ajouts": [(plan.ajouts[0].patient, plan.jour)], "retraits": []}, conv, "lits/places ?")[0]
        note = r.contenu.get("motif", "") if r.performatif == "AGREE" else ""
        self.envoyer("garde", "ACCEPT_PROPOSAL", "accept_garde", {"plan": plan, "gravite": g.nom, "arrivee": arrivee},
                     conv, plan.resume)
        attente = minutes(plan.debut_urgence - arrivee)
        self.annoncer(f"  ✔ {'Nouvelle décision' if reinsertion else 'Décision'} (niveau 4 : planning de garde) : "
                      f"P{p.id} opéré(e) par l'équipe de garde le {jour_txt(plan.jour)} à {hm(plan.debut_urgence)} "
                      f"(attente {attente:.0f} min ; {len(props)} proposition(s) du programme, aucune plus tôt)")
        self._noter_lits(p, note)
        if plan.hors_delai:
            self._alerte_delai(p, g, attente, plan.resume)
        self._enregistrer_urgence(p, g, 4, ID_SALLE_GARDE, ID_EQUIPE_GARDE, plan.debut_urgence, attente,
                                  not plan.hors_delai, plan.cout, plan.resume, len(props), reinsertion, garde=True,
                                  detail=plan.detail)
        return True, {"plan": plan}, plan.resume

    def sur_urgence_confiee_garde(self, msg: Message):
        """Message de l'agent Garde : le système est prévenu qu'une urgence est passée au planning de garde."""
        c = msg.contenu
        alerte = (f"GARDE : urgence {c['gravite']} P{c['patient']} confiée au planning de garde, "
                  f"{jour_txt(c['debut'].date())} {hm(c['debut'])} (programme sans place) — équipe de garde prévenue")
        self.alertes.append(alerte)
        self.annoncer(f"  ⚠ {alerte}")

    def _noter_lits(self, p: Patient, note: str):
        if note:
            self.annoncer(f"    Contraintes signalées : {note}")
            if "hors capacité" in note:
                alerte = f"P{p.id} : aucun lit libre ({note}) -> la cellule de gestion des lits doit trouver un lit d'aval"
                self.alertes.append(alerte)
                self.annoncer(f"  ⚠ {alerte}")

    def _alerte_delai(self, p: Patient, g: Gravite, attente: float, plan_txt: str):
        alerte = (f"URGENCE {g.nom} P{p.id} : délai de {g.delai_max_min} min dépassé (attente {attente:.0f} min) "
                  f"— décision humaine requise (médecin régulateur) ; meilleur plan disponible : {plan_txt}")
        self.alertes.append(alerte)
        self.annoncer(f"  ⚠ {alerte}")

    def _enregistrer_urgence(self, p, g, niveau, salle, chirurgien, debut, attente, dans_delai, cout, plan_txt,
                             nb_props, reinsertion, garde, detail):
        # une ré-insertion remplace la décision précédente (le bilan ne compte qu'une urgence)
        self.decisions = [d for d in self.decisions if not (d["type"] == "urgence" and d["patient"] == p.id)]
        self.decisions.append({"type": "urgence", "heure": self.maintenant, "patient": p.id, "gravite": g.nom,
                               "niveau": niveau, "garde": garde, "salle": salle, "chirurgien": chirurgien,
                               "debut": debut, "attente_min": attente, "dans_delai": dans_delai, "cout": cout,
                               "detail": detail, "plan": plan_txt, "nb_propositions": nb_props,
                               "reprogrammee": reinsertion})

    # ---------- cas A : réoptimisation globale par l'agent Optimisation
    def _etat_global(self, conv) -> dict:
        reps = self.diffuser(AgentSalle, "REQUEST", "etat_programme", {}, conv, "état du programme ?")
        its, creneaux = [], {}
        for r in reps:
            its += r.contenu["interventions"]
            creneaux.update(r.contenu["creneaux"])
        garde = self.envoyer("garde", "REQUEST", "etat_programme", {}, conv, "planning de garde ?")[0]
        attente = list(self.liste_attente)
        return {"maintenant": self.maintenant, "interventions": its, "garde": garde.contenu["interventions"],
                "liste_attente": attente, "creneaux": creneaux, "fenetres": self._fenetres(conv),
                "competents": {it.pid: self.competents(it) for it in its + [i for i, _ in attente] if not it.urgence}}

    def _valider_global(self, mvts: list[dict], conv) -> tuple[bool, str]:
        """Contrôle GROUPÉ : chaque chirurgien vérifie toutes ses modifications d'un coup (patients déplacés
        retirés d'abord, puis ajoutés à leur nouvel horaire), puis l'hébergement vérifie lits et places."""
        par_chir: dict[int, dict] = {}
        for m in mvts:
            it = m["nouveau"]
            par_chir.setdefault(it.chirurgien_id, {"intervalles": [], "retraits": []})["intervalles"].append(
                (it.pid, it.debut, it.fin, it.salle_id))
            if m["etait_place"]:
                par_chir.setdefault(m["ancien"].chirurgien_id, {"intervalles": [], "retraits": []})["retraits"].append(it.pid)
        for cid, contenu in sorted(par_chir.items()):
            r = self.envoyer(f"chir_{cid}", "REQUEST", "verifier_agenda", contenu, conv,
                             f"plan global : {len(contenu['intervalles'])} créneau(x)")[0]
            if r.performatif == "REFUSE":
                return False, f"{self.model.nom_chir(cid)} : {r.contenu['motif']}"
        r = self.envoyer("hebergement", "REQUEST", "evaluer_sejours",
                         {"ajouts": [(m["nouveau"].patient, m["debut"].date()) for m in mvts],
                          "retraits": [m["pid"] for m in mvts if m["etait_place"]]}, conv, "plan global : lits ?")[0]
        if r.performatif == "REFUSE":
            return False, f"hébergement : {r.contenu['motif']}"
        return True, ""

    def reoptimiser(self, conv, motif: str):
        """CAS A : demande à l'agent Optimisation un plan global ; l'applique s'il est validé par les ressources."""
        if not self.p.optimisation_globale:
            return
        etat = dict(self._etat_global(conv), motif=motif)
        r = self.envoyer("optimisation", "REQUEST", "reoptimiser", etat, conv, f"réoptimiser le programme ({motif})")[0]
        trace = r.contenu.get("trace")
        if r.performatif != "PROPOSE":
            if trace is not None:
                self.annoncer(f"  ◇ Optimisation globale : {r.resume}", 2)
            return
        mvts = r.contenu["mouvements"]
        ok, rejet = self._valider_global(mvts, conv)
        if not ok:
            trace.motif_rejet = f"refusé par {rejet}"
            self.envoyer("optimisation", "REJECT_PROPOSAL", "reject_proposal", {}, conv, trace.motif_rejet)
            self.annoncer(f"  ◇ Optimisation globale rejetée ({rejet})", 2)
            return
        self.envoyer("optimisation", "ACCEPT_PROPOSAL", "accept_proposal", {}, conv, "plan global accepté")
        jour = self.maintenant.date()
        # application en deux phases : 1) chaque salle libère les patients qui partent ; 2) elle reçoit les arrivants
        departs: dict[int, list[int]] = {}
        for m in mvts:
            if m["etait_place"]:
                departs.setdefault(m["de"][0], []).append(m["pid"])
        for sid, pids in sorted(departs.items()):
            self.envoyer(f"salle_{sid}", "ACCEPT_PROPOSAL", "accept_proposal",
                         {"plan": Plan(sid, ID_FENETRE_GARDE, jour, {}, retraits=pids)}, conv,
                         f"plan global : libérer {', '.join(f'P{p}' for p in pids)}")
        arrivees: dict[int, list[Intervention]] = {}
        for m in mvts:
            arrivees.setdefault(m["vers"][0], []).append(m["nouveau"])
        for sid, its in sorted(arrivees.items()):
            self.envoyer(f"salle_{sid}", "ACCEPT_PROPOSAL", "accept_proposal",
                         {"plan": Plan(sid, ID_FENETRE_GARDE, jour, {it.pid: it.debut for it in its}, ajouts=its)}, conv,
                         f"plan global : placer {', '.join(f'P{it.pid}' for it in its)}")
        places = {m["pid"] for m in mvts if not m["etait_place"]}
        self.liste_attente = [(it, j) for it, j in self.liste_attente if it.pid not in places]
        trace.applique = True
        details = []
        for m in mvts[:6]:
            a, n = m["ancien"], m["nouveau"]
            avant = f"{jour_txt(a.debut.date())} {hm(a.debut)} S{a.salle_id}" if m["etait_place"] else "liste d'attente"
            details.append(f"P{m['pid']} {avant} → {jour_txt(n.debut.date())} {hm(n.debut)} S{n.salle_id}"
                           + (f" ({self.model.nom_chir(n.chirurgien_id)})" if n.chirurgien_id != a.chirurgien_id else ""))
        from metaheuristiques_sma import NOMS
        self.annoncer(f"  ✦ Optimisation globale ({NOMS[trace.methode]}, {trace.temps_s:.2f} s) : score "
                      f"{trace.cout_actuel:,.0f} → {trace.cout_optimise:,.0f}, {len(mvts)} patient(s) déplacé(s) : "
                      + "; ".join(details) + (" ..." if len(mvts) > 6 else ""))
        self.decisions.append({"type": "reoptimisation", "heure": self.maintenant, "motif": motif,
                               "methode": trace.methode, "gain": trace.cout_actuel - trace.cout_optimise,
                               "patients_deplaces": len(mvts), "patients_sortis_attente": len(places)})

    # ---------- panne
    def sur_transferts_bloques(self, msg: Message):
        conv, fenetres = msg.conversation, msg.contenu["fenetres"]
        reponses = self.diffuser(AgentSalle, "CFP", "cfp_panne", {"fenetres": fenetres, "maintenant": self.maintenant,
                                                                 "agendas": self._agendas(conv)},
                                 conv, "adapter votre programme à la panne")
        retenus, impact = set(), False
        for r in reponses:
            plans = r.contenu.get("plans", [])
            for pl in plans:
                if not (pl.placements or pl.retraits):      # créneau non modifié : seuls les patients en SSPI
                    retenus |= set(pl.retenus_sspi)
            for fid, pids in r.contenu.get("non_resolus", []):
                impact = True
                alerte = (f"Panne : {r.emetteur}, créneau {fid} — " + ", ".join(f"P{x}" for x in pids)
                          + " ne peuvent pas monter au bloc et aucun réordonnancement ne convient -> arbitrage du cadre de bloc")
                self.alertes.append(alerte)
                self.annoncer(f"  ⚠ {alerte}")
            par_creneau: dict[int, list] = {}
            for pl in plans:
                if pl.placements or pl.retraits:
                    par_creneau.setdefault(pl.fenetre_id, []).append((r.emetteur, pl))
            for fid, props in sorted(par_creneau.items()):
                impact = True
                choix = self._choisir(props, conv, lambda pl: (False, pl.cout))
                if choix is None:
                    alerte = f"Panne : aucun plan valide pour {r.emetteur} (créneau {fid}) -> arbitrage du cadre de bloc"
                    self.alertes.append(alerte)
                    self.annoncer(f"  ⚠ {alerte}")
                    continue
                agent, plan, extra, _ = choix
                retenus |= set(plan.retenus_sspi) - set(plan.retraits)   # SSPI : seulement le plan retenu
                retirees = self._appliquer(agent, plan, props, conv)
                self.annoncer(f"  ✔ {plan.resume}  (coût {plan.cout + extra:,.0f})")
                self.decisions.append({"type": "panne", "heure": self.maintenant, "salle": plan.salle_id,
                                       "cout": plan.cout + extra, "detail": plan.detail, "plan": plan.resume})
                self._replacer(retirees, conv)
        if retenus:
            self.annoncer("  ℹ Patients maintenus en salle de réveil en attendant le monte-lit : "
                          + ", ".join(f"P{x}" for x in sorted(retenus)))
        if not impact:
            self.annoncer("  ✔ Aucun (nouveau) patient à brancarder pendant la panne : programme inchangé")
        self.reoptimiser(conv, "panne du monte-lit")

    def sur_transferts_retablis(self, msg: Message):
        conv = msg.conversation
        reponses = self.diffuser(AgentSalle, "CFP", "cfp_compacter",
                                 {"fenetres": msg.contenu["fenetres"], "maintenant": self.maintenant,
                                  "agendas": self._agendas(conv)},
                                 conv, "ré-avancer les patients décalés ?")
        rattrape = False
        for r in reponses:
            for pl in r.contenu.get("plans", []):
                props = [(r.emetteur, pl)]
                if self._choisir(props, conv, lambda x: (False, x.cout)):
                    self._appliquer(r.emetteur, pl, props, conv)
                    rattrape = True
                    self.annoncer(f"  ✔ rattrapage : {pl.resume} (gain {pl.detail.get('gain', 0):,.0f})")
                    self.decisions.append({"type": "rattrapage", "heure": self.maintenant, "salle": pl.salle_id,
                                           "gain": pl.detail.get("gain", 0), "plan": pl.resume})
        rattrape |= self._reavancer(conv)
        if not rattrape:
            self.annoncer("  ✔ Transferts rétablis : aucun patient ne peut être avancé")
        self._relancer_attente(conv, self.maintenant + self.p.preparation_rattrapage_min * MIN)
        self.reoptimiser(conv, "fin de panne")

    def _reavancer(self, conv) -> bool:
        """Rattrapage ENTRE créneaux / salles : un patient fortement décalé (ex. déplacé l'après-midi chez un
        confrère pendant la panne) est remis plus tôt dans la journée si un créneau s'est libéré."""
        apres = self.maintenant + self.p.preparation_rattrapage_min * MIN
        reponses = self.diffuser(AgentSalle, "REQUEST", "lister_decales", {"apres": apres, "seuil_min": 60},
                                 conv, "patients décalés aujourd'hui ?")
        candidats = sorted((it for r in reponses for it in r.contenu.get("interventions", [])),
                           key=lambda i: (-i.patient.priorite, i.debut))
        fait = False
        for it in candidats:
            reponses = self.diffuser(AgentSalle, "CFP", "cfp_replacement",
                                     {"intervention": it, "apres": apres, "fenetres": self._fenetres(conv),
                                      "agendas": self._agendas(conv),
                                      "chirurgiens": self.competents(it), "jour_reference": it.debut_initial.date()},
                                     conv, f"avancer P{it.pid} (actuellement {hm(it.debut)}) ?")
            # rattrapage accepté seulement s'il n'évince personne et si le gain (minutes x priorité) dépasse son coût
            gain = lambda pl: minutes(it.debut - pl.placements[it.pid]) * it.patient.priorite * self.p.c_decalage_min
            props = [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]
                     if pl.fenetre_id != it.fenetre_id and pl.jour == it.debut.date() and not pl.retraits
                     and pl.placements.get(it.pid, it.debut) < it.debut - 30 * MIN and gain(pl) > pl.cout]
            choix = self._choisir(props, conv, lambda pl: (False, pl.cout - gain(pl)))
            if choix is None:
                continue
            agent, plan, _extra, _ = choix
            ancien = f"salle_{it.salle_id}"
            # 1) on libère son créneau actuel, 2) on applique le nouveau plan
            self.envoyer(ancien, "ACCEPT_PROPOSAL", "accept_proposal",
                         {"plan": Plan(it.salle_id, it.fenetre_id, it.debut.date(), {}, retraits=[it.pid])},
                         conv, f"libérer P{it.pid}")
            evinces = self._appliquer(agent, plan, props, conv)
            self.annoncer(f"  ✔ rattrapage : P{it.pid} avancé de {hm(it.debut)} à {hm(plan.placements[it.pid])} — {plan.resume}")
            self.decisions.append({"type": "rattrapage", "heure": self.maintenant, "salle": plan.salle_id,
                                   "patient": it.pid, "plan": plan.resume})
            self._replacer(evinces, conv)
            fait = True
        return fait

    # ---------- replacement (chaque patient déclenche son propre appel d'offres)
    MAX_TOURS_REPLACEMENT = 60

    def appel_offres_replacement(self, it: Intervention, apres: datetime, chirurgiens: list[int], jour_reference: date,
                                 conv, resume: str):
        """Appel d'offres de replacement. Chaque salle ne renvoie que ses meilleures propositions (les plus proches) :
        si les ressources les refusent toutes (lits pleins ces jours-là), on relance en excluant ces jours, jusqu'à
        trouver une date valide. Renvoie (propositions reçues, choix ou None)."""
        exclus, recues = set(), []
        for _ in range(self.MAX_TOURS_REPLACEMENT):
            reponses = self.diffuser(AgentSalle, "CFP", "cfp_replacement",
                                     {"intervention": it, "apres": apres, "fenetres": self._fenetres(conv),
                                      "agendas": self._agendas(conv), "chirurgiens": chirurgiens,
                                      "jour_reference": jour_reference, "jours_exclus": frozenset(exclus)},
                                     conv, resume)
            props = [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]]
            if not props:
                break
            recues += props
            choix = self._choisir(props, conv, lambda pl: (False, pl.cout))
            if choix is not None:
                return recues, choix
            exclus |= {pl.jour for _, pl in props}
        return recues, None

    def _relancer_attente(self, conv, apres: datetime):
        if not self.liste_attente:
            return
        self.annoncer(f"  Nouvelle tentative pour {len(self.liste_attente)} patient(s) en liste d'attente")
        attente, self.liste_attente = self.liste_attente, []
        self._replacer([it for it, _ in attente], conv, apres=apres, references={it.pid: j for it, j in attente})

    def _replacer(self, retirees: list[Intervention], conv, apres: Optional[datetime] = None,
                  references: Optional[dict] = None):
        for it in [i for i in retirees if i.urgence and i.pid in self.urgences_info]:
            retirees = [i for i in retirees if i is not it]
            self._reinserer_urgence(it, conv)               # une urgence garde son délai : appel d'offres urgence
        file = sorted(retirees, key=lambda i: -i.patient.priorite)
        while file:
            it = file.pop(0)
            jour_ref = (references or {}).get(it.pid, it.debut.date())
            debut = apres or self.maintenant + self.p.preparation_rattrapage_min * MIN
            props, choix = self.appel_offres_replacement(it, debut, self.competents(it), jour_ref, conv,
                                                         f"replacer P{it.pid} ({it.patient.duree_bloc} min)")
            if choix is None:
                self.liste_attente.append((it, jour_ref))
                self.annoncer(f"    ↳ P{it.pid} (prio {it.patient.priorite}) : aucune place sur les heures du planning "
                              f"-> liste d'attente")
                self.decisions.append({"type": "attente", "heure": self.maintenant, "patient": it.pid})
                continue
            agent, plan, extra, _ = choix
            evinces = self._appliquer(agent, plan, props, conv)
            self.annoncer(f"    ↳ {plan.resume}")
            nouvelle = plan.ajouts[0]
            self.decisions.append({"type": "replacement", "heure": self.maintenant, "patient": it.pid,
                                   "debut": nouvelle.debut, "salle": plan.salle_id, "chirurgien": nouvelle.chirurgien_id,
                                   "changement_chirurgien": nouvelle.chirurgien_id != nouvelle.chirurgien_initial,
                                   "cout": plan.cout + extra})
            file = sorted(file + evinces, key=lambda i: -i.patient.priorite)   # évincés : moins prioritaires

    def step(self):
        """Proactif : chaque matin à 7 h, relance la liste d'attente."""
        t = self.maintenant
        ouverture = datetime.combine(t.date(), time(7))
        if self.liste_attente and t.date() in self.model.jours_planning and ouverture <= t < ouverture + self.model.pas \
                and self._dernier_matin != t.date():
            self._dernier_matin = t.date()
            self.annoncer(f"\n[{jour_txt(t.date())} {hm(t)}] Relance matinale de la liste d'attente")
            conv = self.model.nouvelle_conversation("ATT")
            self._relancer_attente(conv, t)
            self.reoptimiser(conv, "relance matinale")


# =============================================================================
# 6. LE MODÈLE MESA
# =============================================================================

class BlocOperatoire(mesa.Model):
    """Modèle Mesa : horloge, événements, acheminement des messages, collecte des indicateurs."""

    def __init__(self, instance1: InstanceProbleme, instance2: InstanceNiveau2, solution: SolutionPatients,
                 specialites: Optional[dict[int, str]] = None, chirurgien_garde: Optional[int] = None,
                 parametres: ParametresSMA = ParametresSMA(), batiment: Batiment = Batiment(),
                 verbeux: int = 1, seed: Optional[int] = GRAINE_MESA):
        try:
            super().__init__(rng=seed)          # Mesa >= 3.2
        except TypeError:
            super().__init__(seed=seed)         # versions plus anciennes
        self.instance1, self.instance2, self.parametres = instance1, instance2, parametres
        self.verbeux = verbeux
        self.annuaire: dict[str, AgentSMA] = {}
        self.journal: list[Message] = []
        self.evenements: list[Evenement] = []
        self._actions: list = []                 # Mesa garde des références faibles : on les conserve ici
        self._conv = 0
        self._heure_evenement: Optional[datetime] = None
        self.jours_planning = {cr.jour for cr in instance1.creneaux.values()}
        self.t0 = datetime.combine(min(self.jours_planning), time(0))
        self.pas = timedelta(minutes=parametres.pas_minutes)
        self.specialites = specialites if specialites is not None else {}
        if chirurgien_garde not in instance1.chirurgiens:
            chirurgien_garde = None

        self.traces_locales: list[dict] = []          # cas B : une trace par optimisation locale d'une salle
        self.problemes_locaux: list = []              # problèmes locaux capturés (script de comparaison)
        AgentTriage(self, self.specialites, chirurgien_garde)
        self.regulation = AgentRegulation(self, self.specialites)
        self.logistique = AgentLogistique(self, batiment)
        self.hebergement = AgentHebergement(self, instance2.hebergement)

        fenetres = {sid: [] for sid in instance1.salles}
        for v in instance2.vacations.values():
            if not v.supplementaire:
                fenetres[v.salle_id].append(Fenetre(v.id, v.salle_id, v.debut, datetime.combine(v.jour, v.heure_fin),
                                                    v.chirurgien_id, v.capacite_utile_minutes))
        fid = -1
        for sid in instance1.salles:               # plages d'urgence contiguës fusionnées
            plages = sorted((instance1.creneaux[pl.creneau_id] for pl in instance1.plages_bloc.values()
                             if pl.salle_id == sid and pl.type_plage == "URGENCE"), key=lambda c: (c.jour, c.heure_debut))
            urg: list[Fenetre] = []
            for c in plages:
                d, f = datetime.combine(c.jour, c.heure_debut), datetime.combine(c.jour, c.heure_fin)
                if urg and urg[-1].fin == d:
                    urg[-1] = replace(urg[-1], fin=f, capacite_utile_min=minutes(f - urg[-1].debut))
                else:
                    urg.append(Fenetre(fid, sid, d, f, None, minutes(f - d)))
                    fid -= 1
            fenetres[sid] += urg
        self.salles = {sid: AgentSalle(self, sid, s.nom, fenetres[sid]) for sid, s in instance1.salles.items()}
        self.garde = AgentGarde(self, self.jours_planning)
        from optimisation_sma import AgentOptimisation          # import tardif (optimisation_sma importe ce module)
        self.optimisation = AgentOptimisation(self)
        self.urgences_recues: set[int] = set()          # invariant : chacune doit être programmée
        self.absences: dict[int, list[tuple[datetime, datetime]]] = {}   # chirurgien -> périodes [début, fin[
        self.chirurgiens = {}
        for cid, c in instance1.chirurgiens.items():
            dispo = instance1.disponibilites_chirurgiens.get(cid)
            jours = {instance1.creneaux[k].jour for k in dispo} if dispo else set(self.jours_planning)
            self.chirurgiens[cid] = AgentChirurgien(self, cid, c.nom, jours)
        self.salles = _SallesAvecGarde(self.salles, self.garde)
        self.chirurgiens = _ChirurgiensAvecGarde(self.chirurgiens, self.garde)

        # Ordonnancement initial dans chaque vacation : priorité décroissante puis plus long d'abord
        par_vac: dict[int, list[Patient]] = {}
        for pid, vid in solution.affectations.items():
            if vid is not None and not instance2.vacations[vid].supplementaire:
                par_vac.setdefault(vid, []).append(instance2.patients[pid])
        for vid, patients in par_vac.items():
            v = instance2.vacations[vid]
            t = v.debut
            for pat in sorted(patients, key=lambda x: (-x.priorite, -x.duree_bloc, x.id)):
                it = Intervention(pat, v.salle_id, t, vid)
                self.salles[v.salle_id].interventions[pat.id] = it
                self.chirurgiens[pat.chirurgien_id].agenda[pat.id] = (it.debut, it.fin, v.salle_id)
                self.hebergement.sejours[pat.id] = (pat, v.jour)
                t = it.fin
        self.non_places_initiaux = [pid for pid, v in solution.affectations.items() if v is None]

        self.datacollector = mesa.DataCollector(
            model_reporters={
                "heure": lambda m: m.maintenant,
                "interventions_terminees": lambda m: sum(i.fin <= m.maintenant for i in m.interventions()),
                "salles_actives": lambda m: sum(s.en_cours is not None for s in m.salles.values()),
                "retard_du_jour_min": lambda m: sum(max(0.0, minutes(i.debut - i.debut_initial))
                                                    for i in m.interventions()
                                                    if not i.urgence and i.debut.date() == i.debut_initial.date()),
                "reportes_ou_en_attente": lambda m: len(m.regulation.liste_attente) + sum(
                    i.debut.date() != i.debut_initial.date() for i in m.interventions() if not i.urgence),
                "urgences_programmees": lambda m: sum(i.urgence for i in m.interventions()),
                "liste_attente": lambda m: len(m.regulation.liste_attente),
                "monte_lit_disponible": lambda m: int(m.logistique.monte_lit_disponible()),
                "lits_occupes": lambda m: m.hebergement.occupation()[0].get(m.maintenant.date(), 0),
            },
            agenttype_reporters={AgentSalle: {"salle": "nom_affiche", "patient_en_cours": "en_cours"}},
        )

    # ------------------------------------------------------------------ constructeurs
    @classmethod
    def depuis_v28(cls, lundi: date, nb_semaines: int = NB_SEMAINES_SCENARIOS_SMA,
                   solution: Optional[SolutionPatients] = None,
                   instances: Optional[tuple[InstanceProbleme, InstanceNiveau2]] = None, **kw) -> "BlocOperatoire":
        """Planning réel planning_vacations_v28 à partir de `lundi` (parité déduite de la date).
        `solution` : affectation N2 de vos métaheuristiques / de l'hybridation, calculée sur
        `instances` (sinon : glouton multi-départ commun). Les plages URGENCE sont tenues par le
        « chirurgien d'urgence » anonyme (id 900)."""
        i1, i2 = instances or construire_instances_v28(lundi, nb_semaines)
        kw.setdefault("specialites", specialites_par_id())
        kw.setdefault("chirurgien_garde", ID_CHIR_URGENCE)
        return cls(i1, i2, solution or construire_meilleure_affectation_initiale(i2), **kw)

    # ------------------------------------------------------------------ absences des chirurgiens
    def chirurgien_absent(self, cid: int, debut: datetime, fin: datetime) -> bool:
        """Le chirurgien est-il absent à un moment de [debut, fin[ ?"""
        return any(chevauche(debut, fin, a, b) for a, b in self.absences.get(cid, ()))

    def fenetre_fermee(self, fen: "Fenetre") -> bool:
        """Vacation fermée : son chirurgien est absent (les plages d'urgence restent ouvertes)."""
        return fen.chirurgien_id is not None and self.chirurgien_absent(fen.chirurgien_id, fen.debut, fen.fin)

    # ------------------------------------------------------------------ temps
    @property
    def maintenant(self) -> datetime:
        if self._heure_evenement is not None:
            return self._heure_evenement
        return self.t0 + self.time * self.pas

    def _temps(self, t: datetime) -> float:
        return (t - self.t0) / self.pas

    def planifier_action(self, heure: datetime, fonction):
        """Planifie un appel à une heure précise (événement discret Mesa)."""
        def action():
            self._heure_evenement = heure
            try:
                fonction()
            finally:
                self._heure_evenement = None
        self._actions.append(action)
        return self.schedule_event(action, at=max(self._temps(heure), self.time + 1e-9))

    def planifier(self, evt: Evenement):
        """Ajoute un aléa à la simulation : il sera traité à son heure."""
        self.evenements.append(evt)
        self.planifier_action(evt.heure, functools.partial(self._declencher, evt))

    def executer_jusqu_a(self, heure: datetime):
        self.run_until(self._temps(heure))

    def step(self):
        self.agents.do("step")
        t = self.maintenant
        if t.date() in self.jours_planning and time(7) <= t.time() <= time(20):
            self.datacollector.collect(self)

    # ------------------------------------------------------------------ messages
    def nouvelle_conversation(self, prefixe: str) -> str:
        self._conv += 1
        return f"{prefixe}-{self._conv:03d}"

    def acheminer(self, msg: Message) -> list[Message]:
        self._tracer(msg)
        reponses = self.annuaire[msg.destinataire].recevoir(msg)
        for r in reponses:
            self._tracer(r)
        return reponses

    def _tracer(self, msg: Message):
        self.journal.append(msg)
        if self.verbeux >= 2:
            print(f"    {hm(msg.heure)} {msg.emetteur:>12} → {msg.destinataire:<12} {msg.performatif:<15} "
                  f"{msg.sujet:<20} {msg.resume}")

    def annoncer(self, texte: str, niveau: int = 1):
        if self.verbeux >= niveau:
            print(texte)

    def nom_chir(self, cid) -> str:
        if cid == ID_EQUIPE_GARDE:
            return "Garde"
        return self.chirurgiens[cid].nom_affiche if cid in self.chirurgiens else f"chir {cid}"

    def _declencher(self, evt: Evenement):
        t = evt.heure
        if isinstance(evt, ArriveeUrgence):
            conv = self.nouvelle_conversation("URG")
            p = evt.patient
            self.urgences_recues.add(p.id)
            self.annoncer(f"\n[{jour_txt(t.date())} {hm(t)}] {conv} — URGENCE : P{p.id} {p.nom} ({p.specialite}, "
                          f"{p.diagnostic or 'diagnostic n.c.'}, {p.duree_bloc} min, "
                          f"{'ambulatoire' if p.ambulatoire else 'hospitalisé'})")
            self.acheminer(Message("INFORM", "accueil", "triage", "arrivee_urgence", {"evenement": evt}, conv, t, f"P{p.id}"))
        else:
            conv = self.nouvelle_conversation("ASC")
            titre = {PanneAscenseur: "PANNE ASCENSEUR", ProlongationPanne: "PROLONGATION DE PANNE",
                     FinPanne: "FIN DE PANNE"}[type(evt)]
            fin = getattr(evt, "fin_estimee", None)
            self.annoncer(f"\n[{jour_txt(t.date())} {hm(t)}] {conv} — {titre} : {evt.ascenseur}"
                          + (f" (retour estimé {hm(fin)})" if fin else ""))
            self.acheminer(Message("INFORM", "technique", "logistique", "panne", {"evenement": evt}, conv, t, titre.lower()))

    # ------------------------------------------------------------------ consultation
    def interventions(self) -> list[Intervention]:
        return sorted((i for s in self.salles.values() for i in s.interventions.values()), key=lambda i: (i.debut, i.salle_id))

    def afficher_jour(self, jour: date, titre: str = ""):
        print(f"\n  {'═' * 92}\n  {titre or 'PROGRAMME'} — {jour_txt(jour)}\n  {'═' * 92}")
        for salle in self.salles.values():
            print(f"  {salle.nom_affiche}")
            for fen in sorted((f for f in salle.creneaux.values() if f.jour == jour), key=lambda f: f.debut):
                items = salle.du_creneau(fen.id)
                if fen.urgence and not items:
                    continue
                cadre = "plage URGENCES" if fen.urgence else f"vacation {self.nom_chir(fen.chirurgien_id)}"
                print(f"   ┌ {hm(fen.debut)}-{hm(fen.fin)} {cadre}")
                for it in items:
                    d = int(minutes(it.debut - it.debut_initial))
                    marque = "★ URGENCE " if it.urgence else ""
                    if not it.urgence and it.debut_initial.date() != it.debut.date():
                        marque += f"↻ reporté du {it.debut_initial:%d/%m} "
                    elif d:
                        marque += f"{'↷ décalé +' if d > 0 else '↶ avancé '}{abs(d)} min "
                    if it.chirurgien_id != it.chirurgien_initial:
                        marque += f"⇄ au lieu de {self.nom_chir(it.chirurgien_initial)} "
                    print(f"   │ {hm(it.debut)}-{hm(it.fin)}  P{it.pid:<5} {self.nom_chir(it.chirurgien_id):<7} "
                          f"{it.patient.duree_bloc:>3} min  {'amb. ' if it.patient.ambulatoire else 'hosp.'} "
                          f"prio {it.patient.priorite}  {marque}")
        garde = self.garde.du_jour(jour)
        if garde:
            print(f"  Planning de garde (à partir de {hm(self.parametres.garde_soir)} les jours de programme)")
            for it in garde:
                d = self.regulation.urgences_info.get(it.pid)
                print(f"   │ {hm(it.debut)}-{hm(it.fin)}  P{it.pid:<5} {'Garde':<7} {it.patient.duree_bloc:>3} min  "
                      f"{'amb. ' if it.patient.ambulatoire else 'hosp.'} ★ URGENCE {d[2].nom if d else ''}")
        lits, places = self.hebergement.occupation()
        h = self.instance2.hebergement
        print(f"  Hébergement : {lits.get(jour, 0)}/{h.cap_lits} lits (+{h.reserve_lits} réserve), "
              f"{places.get(jour, 0)}/{h.cap_places} places ambulatoires")

    def bilan(self) -> dict[str, Any]:
        its = self.interventions()
        prog = [i for i in its if not i.urgence]
        meme_jour = [i for i in prog if i.debut != i.debut_initial and i.debut.date() == i.debut_initial.date()]
        urg = [d for d in self.regulation.decisions if d["type"] == "urgence"]
        perf: dict[str, int] = {}
        for m in self.journal:
            perf[m.performatif] = perf.get(m.performatif, 0) + 1
        niveaux: dict[int, int] = {}
        for d in urg:
            niveaux[d["niveau"]] = niveaux.get(d["niveau"], 0) + 1
        return {
            "evenements": len(self.evenements),
            "urgences_recues": len(self.urgences_recues),
            "urgences_programmees": len(urg),
            "urgences_non_programmees": len(self.urgences_non_programmees()),     # invariant : doit valoir 0
            # anciens noms, conservés pour l'interface (vues/urgences.py) et demo_sma_urgences.py
            "urgences_inserees": len(urg),
            "urgences_refusees": 0,                                                  # plus aucun refus / transfert
            "urgences_dans_delai": sum(d["dans_delai"] for d in urg),
            "urgences_hors_delai": sum(not d["dans_delai"] for d in urg),
            "urgences_escaladees": sum(d["niveau"] > 0 for d in urg),
            "urgences_au_planning_de_garde": sum(d["garde"] for d in urg),
            "urgences_par_niveau": dict(sorted(niveaux.items())),
            "attente_moyenne_urgence_min": round(sum(d["attente_min"] for d in urg) / len(urg), 1) if urg else 0.0,
            "attente_max_urgence_min": round(max((d["attente_min"] for d in urg), default=0.0)),
            "patients_decales": sum(i.debut > i.debut_initial for i in meme_jour),
            "patients_avances": sum(i.debut < i.debut_initial for i in meme_jour),
            "minutes_de_decalage_cumulees": round(sum(abs(minutes(i.debut - i.debut_initial)) for i in meme_jour)),
            "patients_reportes_autre_jour": sum(i.debut.date() != i.debut_initial.date() for i in prog),
            "patients_repris_par_un_confrere": sum(i.chirurgien_id != i.chirurgien_initial for i in prog),
            "patients_en_liste_attente": len(self.regulation.liste_attente),
            "erreurs_de_coherence": len(self.verifier_coherence()),
            "alertes": list(self.regulation.alertes),
            "messages_echanges": len(self.journal),
            "messages_par_performatif": perf,
            # --- architecture hybride ---
            "score_programme": round(self.score_programme()["total"]),
            "optimisations_locales": len(self.traces_locales),
            "ameliorations_locales": sum(t["ameliore"] for t in self.traces_locales),
            "reoptimisations_globales": len(self.optimisation.historique),
            "reoptimisations_appliquees": sum(t.applique for t in self.optimisation.historique),
            "gain_optimisation_globale": round(sum(t.cout_actuel - t.cout_optimise for t in self.optimisation.historique
                                                   if t.applique)),
            "temps_optimisation_s": round(sum(t.temps_s for t in self.optimisation.historique)
                                          + sum(t["temps_s"] for t in self.traces_locales), 2),
        }

    def score_programme(self) -> dict[str, float]:
        """Score GLOBAL du planning (à minimiser), indépendant de l'heure : il compte tous les patients, passés
        compris, avec les poids du SMA et de la fonction N2 commune. Sert à comparer les configurations."""
        P, w = self.parametres, POIDS_N2
        det = {"decalages": 0.0, "reports": 0.0, "changements_chirurgien": 0.0, "liste_attente": 0.0,
               "attente_urgences": 0.0, "lits_places": 0.0}
        for it in self.interventions():
            if it.urgence:
                continue
            prio, jours = it.patient.priorite, (it.debut.date() - it.debut_initial.date()).days
            if jours == 0:
                d = minutes(it.debut - it.debut_initial)
                det["decalages"] += max(0.0, d) * prio * P.c_decalage_min + max(0.0, -d) * prio * P.c_avance_min
            else:
                det["reports"] += P.c_deprogrammation * prio + P.c_report_jour * prio * abs(jours)
            if it.chirurgien_id != it.chirurgien_initial:
                det["changements_chirurgien"] += P.c_changement_chirurgien
        for it, _ in self.regulation.liste_attente:
            det["liste_attente"] += P.c_deprogrammation * it.patient.priorite + w.non_place
        for d in self.regulation.decisions:
            if d["type"] == "urgence":
                det["attente_urgences"] += d["attente_min"] * GRAVITES[d["gravite"]].poids_attente
        lits, places = self.hebergement.occupation()
        h = self.instance2.hebergement
        det["lits_places"] = (sum(max(0, o - h.cap_lits) for o in lits.values()) * w.lit
                              + sum(max(0, o - h.cap_places) for o in places.values()) * w.place)
        det["total"] = sum(det.values())
        return det

    def urgences_non_programmees(self) -> list[int]:
        programmees = {i.pid for i in self.interventions() if i.urgence} | set(self.garde.interventions)
        return sorted(self.urgences_recues - programmees)

    def afficher_bilan(self):
        b = self.bilan()
        print(f"\n  {'═' * 92}\n  BILAN DU SYSTÈME MULTI-AGENT\n  {'═' * 92}")
        print(f"  Événements traités                 : {b['evenements']}")
        print(f"  Urgences reçues / programmées      : {b['urgences_recues']} / {b['urgences_programmees']}"
              f"  (non programmées : {b['urgences_non_programmees']} — doit valoir 0)")
        print(f"  ... dans le délai / hors délai     : {b['urgences_dans_delai']} / {b['urgences_hors_delai']}, "
              f"attente moyenne {b['attente_moyenne_urgence_min']} min (max {b['attente_max_urgence_min']} min)")
        print(f"  ... escaladées / planning de garde : {b['urgences_escaladees']} / {b['urgences_au_planning_de_garde']}"
              f"  (par niveau : {b['urgences_par_niveau']})")
        print(f"  Patients décalés / avancés         : {b['patients_decales']} / {b['patients_avances']} "
              f"({b['minutes_de_decalage_cumulees']} min cumulées)")
        print(f"  Patients reportés à un autre jour  : {b['patients_reportes_autre_jour']}")
        print(f"  Patients repris par un confrère    : {b['patients_repris_par_un_confrere']}")
        print(f"  Patients en liste d'attente        : {b['patients_en_liste_attente']}")
        print(f"  Contrôle de cohérence              : {'OK' if not b['erreurs_de_coherence'] else str(b['erreurs_de_coherence']) + ' erreur(s)'}"
              f" (salles, chirurgiens, heures du planning, agendas, séjours, urgences programmées)")
        print(f"  Messages échangés                  : {b['messages_echanges']}  {b['messages_par_performatif']}")
        print(f"  Optimisation locale (Salles, {self.parametres.methode_locale}) : {b['ameliorations_locales']} plan(s) "
              f"amélioré(s) sur {b['optimisations_locales']}")
        print(f"  Optimisation globale ({self.parametres.optimisation_globale}) : {b['reoptimisations_appliquees']} plan(s) "
              f"appliqué(s) sur {b['reoptimisations_globales']}, gain {b['gain_optimisation_globale']:,}")
        print(f"  Score global du planning           : {b['score_programme']:,} (à minimiser)   "
              f"temps d'optimisation {b['temps_optimisation_s']} s")
        for a in b["alertes"]:
            print(f"  ⚠ {a}")

    def verifier_coherence(self) -> list[str]:
        """Contrôle indépendant : chevauchements salle / chirurgien, heures du planning, agendas, séjours."""
        erreurs, its = [], self.interventions()
        for k, a in enumerate(its):
            for b in its[k + 1:]:
                if b.debut >= a.fin:
                    break
                if a.salle_id == b.salle_id:
                    erreurs.append(f"salle {a.salle_id} : P{a.pid} et P{b.pid} se chevauchent")
                if a.chirurgien_id == b.chirurgien_id:
                    erreurs.append(f"{self.nom_chir(a.chirurgien_id)} : P{a.pid} et P{b.pid} en même temps")
        for i in its:
            f = self.salles[i.salle_id].creneaux[i.fenetre_id]
            if not (f.debut <= i.debut and i.fin <= f.fin):
                erreurs.append(f"P{i.pid} hors des heures du planning")
            if not f.urgence and f.chirurgien_id != i.chirurgien_id:
                erreurs.append(f"P{i.pid} opéré hors de la vacation de son chirurgien")
        for cid, ag in self.chirurgiens.items():
            if {i.pid: (i.debut, i.fin, i.salle_id) for i in its if i.chirurgien_id == cid} != ag.agenda:
                erreurs.append(f"agenda de {ag.nom_affiche} désynchronisé")
        garde = sorted(self.garde.interventions.values(), key=lambda i: i.debut)
        for a, b in zip(garde, garde[1:]):
            if b.debut < a.fin:
                erreurs.append(f"salle de garde : P{a.pid} et P{b.pid} se chevauchent")
        for i in garde:
            if not self.garde.en_garde(i.debut, i.gravite):
                erreurs.append(f"P{i.pid} programmé en garde hors des heures de garde")
        if {i.pid: i.debut.date() for i in its + garde} != {pid: j for pid, (_, j) in self.hebergement.sejours.items()}:
            erreurs.append("séjours de l'hébergement désynchronisés")
        for pid in self.urgences_non_programmees():
            erreurs.append(f"urgence P{pid} reçue mais NON programmée")
        return erreurs

    def exporter_journal(self, chemin: Union[str, Path]) -> Path:
        def ser(o):
            if isinstance(o, (datetime, date, time)):
                return o.isoformat()
            if isinstance(o, dict):
                return {str(k): ser(v) for k, v in o.items()}
            if isinstance(o, (list, tuple, set)):
                return [ser(v) for v in o]
            return o
        donnees = {"bilan": self.bilan(), "decisions": ser(self.regulation.decisions),
                   "messages": [{"heure": ser(m.heure), "conversation": m.conversation, "performatif": m.performatif,
                                 "de": m.emetteur, "a": m.destinataire, "sujet": m.sujet, "resume": m.resume}
                                for m in self.journal]}
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return chemin

    def tracer_gantt(self, jour: date, chemin: Union[str, Path], titre: str = "",
                     panne: Optional[tuple[datetime, datetime]] = None):
        """Gantt de la journée : créneaux du planning en pointillés, urgences en rouge, panne grisée."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch

        palette = ["#2a78d6", "#1baf7a", "#eb6834", "#8a5cd1", "#c9a227", "#3aa6b9", "#d1497a", "#6b7a8f"]
        salles = list(self.salles.values()) + ([self.garde] if self.garde.du_jour(jour) else [])
        du_jour = sorted({it.chirurgien_id for s in salles for it in s.du_jour(jour)}
                         | {f.chirurgien_id for s in salles for f in getattr(s, "creneaux", {}).values()
                            if f.jour == jour and not f.urgence})
        couleur = {cid: palette[k % len(palette)] for k, cid in enumerate(du_jour)}   # couleurs des praticiens du jour
        fig, ax = plt.subplots(figsize=(13, 1.1 * len(salles) + 1.6))
        x = lambda t: t.hour + t.minute / 60
        if panne:
            ax.axvspan(x(panne[0]), x(panne[1]), color="#b0b0b0", alpha=0.25, lw=0)
            ax.text(x(panne[0]) + 0.05, -0.6, "monte-lit en panne", fontsize=8, color="#555")
        for k, s in enumerate(salles):
            y = len(salles) - 1 - k
            for f in getattr(s, "creneaux", {}).values():
                if f.jour == jour:
                    ax.barh(y, minutes(f.fin - f.debut) / 60, left=x(f.debut), height=0.86, color="none",
                            edgecolor="#999" if f.urgence else couleur[f.chirurgien_id], linestyle="--", lw=1)
            for it in s.du_jour(jour):
                ax.barh(y, it.patient.duree_bloc / 60, left=x(it.debut), height=0.6,
                        color="#d62728" if it.urgence else couleur[it.chirurgien_id], edgecolor="white",
                        hatch="//" if it.patient.ambulatoire else None, lw=1)
                ax.text(x(it.debut) + it.patient.duree_bloc / 120, y, f"P{it.pid}", ha="center", va="center",
                        fontsize=7, color="white")
        ax.set_yticks(range(len(salles)))
        ax.set_yticklabels([s.nom_affiche for s in reversed(salles)])
        fin_h = max([17.5] + [x(it.fin) + 0.25 for it in self.garde.du_jour(jour)])
        ax.set_xlim(7.5, min(24.0, fin_h))
        ax.set_xticks(range(8, int(min(24.0, fin_h)) + 1))
        ax.set_xticklabels([f"{h}h" for h in range(8, int(min(24.0, fin_h)) + 1)])
        for cote in ("top", "right", "left"):
            ax.spines[cote].set_visible(False)
        ax.grid(axis="x", color="#e4e3df")
        ax.set_axisbelow(True)
        ax.set_title(titre or jour_txt(jour), loc="left", fontsize=11)
        chirs = sorted({it.chirurgien_id for s in salles for it in s.du_jour(jour) if not it.urgence}
                       | {f.chirurgien_id for s in salles for f in getattr(s, "creneaux", {}).values()
                          if f.jour == jour and not f.urgence})
        ax.legend(handles=[Patch(color=couleur[c], label=self.nom_chir(c)) for c in chirs]
                  + [Patch(color="#d62728", label="urgence"),
                     Patch(facecolor="white", edgecolor="#555", hatch="//", label="ambulatoire")],
                  loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=min(8, len(chirs) + 2), frameon=False, fontsize=8)
        fig.tight_layout()
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(chemin, dpi=150, facecolor="white")
        plt.close(fig)
        return chemin

    def tracer_indicateurs(self, chemin: Union[str, Path], jour: Optional[date] = None):
        """Courbes du DataCollector Mesa (retard cumulé, salles actives, monte-lit, liste d'attente)."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        df = self.datacollector.get_model_vars_dataframe()
        if jour is not None:
            df = df[df.heure.map(lambda t: t.date() == jour)]
        heures = df.heure.map(lambda t: t.hour + t.minute / 60)
        fig, axes = plt.subplots(4, 1, figsize=(11, 8), sharex=True)
        series = [("retard_du_jour_min", "Retard cumulé\ndans la journée (min)", "#eb6834"),
                  ("salles_actives", "Salles en activité", "#2a78d6"),
                  ("monte_lit_disponible", "Monte-lit\ndisponible", "#1baf7a"),
                  ("reportes_ou_en_attente", "Patients reportés\nou en attente", "#d1497a")]
        for ax, (col, nom, c) in zip(axes, series):
            ax.step(heures, df[col], where="post", color=c, lw=2)
            ax.set_ylabel(nom, fontsize=8)
            for cote in ("top", "right"):
                ax.spines[cote].set_visible(False)
            ax.grid(color="#e4e3df")
        axes[-1].set_xlabel("heure")
        fig.suptitle(f"Indicateurs collectés par Mesa{' — ' + jour_txt(jour) if jour else ''}", x=0.01, ha="left")
        fig.tight_layout()
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(chemin, dpi=150, facecolor="white")
        plt.close(fig)
        return chemin
