# -*- coding: utf-8 -*-
"""
sma/sma_urgences.py — Système MULTI-AGENT de gestion des aléas du bloc opératoire (Mesa >= 3.0)
==================================================================================================

Ce fichier ne contient QUE le SMA. Il réutilise, sans les recopier :
    planning_vacations/structures_communes.py   Patient, Vacation, InstanceNiveau2, glouton N2...
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

Règles : on n'opère que pendant les heures du planning (vacations + plages URGENCE). Une urgence vitale
sans solution dans le délai est transférée ; une non vitale est programmée plus tard avec une alerte.

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
import random
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional, Union

import mesa

# --- accès aux fichiers du dépôt : commun/ (structures_communes.py partagé), planning_vacations/ (planning v28)
_RACINE = Path(__file__).resolve().parents[1]
if str(_RACINE / "commun") not in sys.path:
    sys.path.insert(0, str(_RACINE / "commun"))
for _dossier in (_RACINE / "planning_vacations", _RACINE / "metaheuristiques"):
    if _dossier.is_dir() and str(_dossier) not in sys.path:
        sys.path.append(str(_dossier))

import planning_vacations_v28 as V28
from structures_communes import (
    GRAINE_PATIENTS, JOURS_FR, Chirurgien, InstanceNiveau2, InstanceProbleme, ParametresHebergement, Patient,
    PlageBloc, SolutionPatients, construire_meilleure_affectation_initiale, generer_patients_etude,
    jours_occupation, type_semaine,
)

MIN = timedelta(minutes=1)


# =============================================================================
# 0. PASSERELLE PLANNING v28 -> SMA
# =============================================================================
# * Les vacations du pseudo-chirurgien URGENCE (id 900) deviennent des plages "URGENCE" où le SMA insère les
#   urgences ; elles sont tenues par un « chirurgien d'urgence » anonyme (le fichier ne dit pas qui opère).
# * Les plages LIBRE (id 901) sont ignorées ; les patients ne sont générés que pour les vrais chirurgiens.
# * Plusieurs semaines : les ids du modèle v28 sont décalés de 100 par semaine.
# * Spécialités : HYPOTHÈSE reprise du jeu de test, à compléter.

ID_CHIR_URGENCE = V28.ID_URGENCE          # 900
ID_PAR_NOM = V28.ID_PAR_NOM                # code praticien -> id (ex. ID_PAR_NOM["CT"])
DECALAGE_ID_SEMAINE = 100

# HYPOTHÈSE (jeu de test) — à compléter dès que les spécialités réelles sont connues
SPECIALITES_V28 = {"CT": "Orthopédie", "MO": "Orthopédie", "LZ": "Main", "HA": "Vasculaire", "JE": "Rachis"}


def specialites_par_id() -> dict[int, str]:
    return {V28.ID_PAR_NOM[n]: s for n, s in SPECIALITES_V28.items()}


def construire_instances_v28(lundi: date, nb_semaines: int = 2, patients: Optional[dict] = None,
                             graine: int = GRAINE_PATIENTS,
                             hebergement: ParametresHebergement = ParametresHebergement()
                             ) -> tuple[InstanceProbleme, InstanceNiveau2]:
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
            for p in generer_patients_etude(vac_reelles, graine + 97 * k).values():
                patients_generes[pid] = replace(p, id=pid, date_min=lundi_k, nom=f"Patient {pid:03d}",
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


GRAVITES = {
    "vitale": Gravite("vitale", 60, 15, 100.0),
    "urgente": Gravite("urgente", 360, 30, 10.0),
    "differable": Gravite("differable", 24 * 60, 60, 1.0),
}


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
    c_lit_depassement: float = 5000.0
    c_report_jour: float = 100.0        # par jour de report, x priorité
    max_deprogrammations: int = 3
    propositions_par_salle: int = 4


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
            for d2, f2, s2, pid2 in tous:
                if pid2 != pid and chevauche(d, f, d2, f2):
                    motif = f"déjà au bloc (salle {s2}) de {hm(d2)} à {hm(f2)}"
                    return msg.reponse("REFUSE", {"motif": motif}, motif)
        astreinte = any(d.date() not in self.jours_presence for _, d, _, _ in proposes)
        return msg.reponse("AGREE", {"cout": self.p.c_astreinte if astreinte else 0.0},
                           "rappel d'astreinte" if astreinte else "disponible")

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

    def _sequencer(self, items, minimums, t0, fenetres, en_liste: bool):
        """Placement à la suite depuis t0 ; en_liste=True : au plus tôt réalisable d'abord (ordre initial
        en cas d'égalité) -> les ambulatoires passent devant les hospitalisés bloqués par l'ascenseur."""
        t, restant, res = t0, list(items), []
        while restant:
            choix = None
            for it in (restant if en_liste else restant[:1]):
                s = premier_transfert_possible(max(t, minimums[it.pid]), fenetres.get(it.origine, []),
                                               self.p.transfert_min)
                if choix is None or (s, it.debut) < choix[0]:
                    choix = ((s, it.debut), it, s)
            _, it, s = choix
            restant.remove(it)
            res.append((it, s))
            t = s + it.duree
        return res

    def _evaluer(self, fen: Fenetre, placement, retraits, fenetres, ctx: dict) -> Plan:
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
            cout += 1e9
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
        morceaux += [f"P{it.pid} déprogrammé" for it in retraits]
        cadre = "plage urgences" if fen.urgence else f"vacation {self.model.nom_chir(fen.chirurgien_id)}"
        return (f"{self.nom_affiche} {jour_txt(fen.jour)} ({cadre} {hm(fen.debut)}-{hm(fen.fin)}) : "
                + (", ".join(morceaux) or "aucun changement"))

    def _avec_deprogrammations(self, fen, items, construire, fenetres, ctx) -> list[Plan]:
        """Variante sans déprogrammation, puis jusqu'à k déprogrammations gloutonnes."""
        plans, courant, retires = [], list(items), []
        base = self._evaluer(fen, construire(courant), retires, fenetres, ctx)
        if base.cout < 1e9:
            plans.append(base)
        meilleur_cout = base.cout
        proteges = {a.pid for a in ctx.get("ajouts", [])}
        # une urgence déjà insérée n'est jamais déprogrammée... sauf en cas de panne (ctx « urgences_deplacables »)
        # où elle ne peut physiquement plus monter au bloc : elle sera alors ré-insérée ailleurs par la régulation.
        urg_ok = ctx.get("urgences_deplacables", False)
        for _ in range(self.p.max_deprogrammations):
            meilleur = None
            for it in courant:
                if (it.urgence and not urg_ok) or it.pid in proteges:   # un patient programmé « urgent » reste déprogrammable
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
            if plan.cout < 1e9 and plan.cout < meilleur_cout:
                plans.append(plan)
                meilleur_cout = plan.cout
        return plans

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
            if fen.jour not in c["jours"] or fen.fin <= c["t_min"]:
                continue
            # vacation : opérée par SON chirurgien s'il est compétent ; plage d'urgence : tout chirurgien compétent
            chirs = c["chirurgiens"] if fen.urgence else [fen.chirurgien_id] if fen.chirurgien_id in c["chirurgiens"] else []
            for cid in chirs:
                patient = replace(c["patient"], chirurgien_id=cid)
                t_min = premier_transfert_possible(max(c["t_min"], fen.debut), fenetres.get("urgences", []),
                                                   self.p.transfert_min)
                if t_min + timedelta(minutes=patient.duree_bloc) > fen.fin:
                    continue
                libres, t0 = self._etat_creneau(fen, maintenant)
                nouvelle = Intervention(patient, self.salle_id, t_min, fen.id, urgence=True,
                                        chirurgien_initial=c["patient"].chirurgien_id)
                ctx = dict(c["ctx"], pid_nouveau=patient.id, ajouts=[nouvelle])
                minimums = {i.pid: i.debut for i in libres} | {patient.id: t_min}
                for pos in range(len(libres) + 1):
                    ordre = libres[:pos] + [nouvelle] + libres[pos:]
                    construire = lambda its, m=minimums, t=t0: self._sequencer(its, m, t, fenetres, False)
                    plans += self._avec_deprogrammations(fen, ordre, construire, fenetres, ctx)
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
            if fen.jour not in jours or fen.fin <= maintenant:
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
            avant = len(plans)
            for en_liste in (True, False):         # réordonner (ambulatoires d'abord) OU simplement décaler
                construire = lambda its, m=minimums, t=t0, l=en_liste: self._sequencer(its, m, t, fenetres, l)
                plans += self._avec_deprogrammations(fen, libres, construire, fenetres, ctx)
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
            if fen.jour != maintenant.date() or fen.fin <= maintenant:
                continue
            libres, t0 = self._etat_creneau(fen, maintenant)
            if not any(i.debut > i.debut_initial or i.urgence for i in libres):
                continue
            minimums = {i.pid: min(max(pret, fen.debut) if i.urgence else
                                   max(pret, fen.debut, i.debut_initial - self.p.avance_max_min * MIN), i.debut)
                        for i in libres}
            ctx = {"reference_initiale": True, "ajouts": []}
            actuel = self._evaluer(fen, [(i, i.debut) for i in libres], [], fenetres, ctx)
            plan = self._evaluer(fen, self._sequencer(libres, minimums, t0, fenetres, True), [], fenetres, ctx)
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
                placement = self._sequencer(restants + [nouvelle], minimums, t0, fenetres, False)
                plan = self._evaluer(fen, placement, retires, fenetres, {"ajouts": [nouvelle], "couts_fixes": fixes})
                if plan.cout < 1e9:
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
        self._dernier_matin: Optional[date] = None

    def competents(self, it: Intervention) -> list[int]:
        """Chirurgiens pouvant opérer ce patient : son chirurgien et ceux de la même spécialité."""
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

    def _choisir(self, propositions, conv, cle_tri):
        valides = []
        for agent, plan in sorted(propositions, key=lambda x: cle_tri(x[1])):
            ok, extra, motif = self._valider(plan, conv)
            if ok:
                valides.append((agent, plan, extra, motif))
            else:
                self.annoncer(f"    ✗ rejetée ({motif}) : {plan.resume}", 2)
        if not valides:
            return None
        return min(valides, key=lambda x: (cle_tri(x[1])[0], x[1].cout + x[2]))

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
        return msg.reponse("AGREE" if ok else "REFUSE", contenu, resume)

    def _reinserer_urgence(self, it: Intervention, conv):
        """Urgence déjà programmée mais rendue impossible (ex. monte-lit en panne) : nouvel appel d'offres,
        avec le MÊME délai maximal (compté depuis l'arrivée aux urgences)."""
        p, arrivee, g, chirurgiens = self.urgences_info[it.pid]
        self.annoncer(f"    ↳ urgence P{it.pid} ne peut plus monter au bloc à {hm(it.debut)} : nouvel appel d'offres")
        t_min = max(arrivee + g.preparation_min * MIN, self.maintenant + self.p.transfert_min * MIN)
        self._inserer_urgence(p, arrivee, g, chirurgiens, conv, t_min=t_min, reinsertion=True)

    def _inserer_urgence(self, p: Patient, arrivee: datetime, g: Gravite, chirurgiens: list[int], conv,
                         t_min: Optional[datetime] = None, reinsertion: bool = False):
        c = {"arrivee": arrivee, "chirurgiens": chirurgiens}
        maintenant = self.maintenant
        fenetres = self._fenetres(conv)
        t_min = t_min or arrivee + g.preparation_min * MIN
        limite = arrivee + g.delai_max_min * MIN
        futurs = sorted(j for j in self.model.jours_planning if j >= t_min.date())
        dans_delai = [j for j in futurs if j <= limite.date()]
        jours = set(dans_delai + [j for j in futurs if j not in dans_delai][:1])   # + jour suivant en secours
        ctx = {"arrivee": c["arrivee"], "limite": limite, "poids_attente": g.poids_attente}
        # 1er appel d'offres : jours dans le délai (+ le jour suivant) ; si rien ne convient et que l'urgence
        # n'est pas vitale, 2e appel d'offres sur tout l'horizon (elle sera opérée hors délai, avec alerte).
        # Une urgence vitale sans solution dans le délai est transférée.
        essais = [jours] + ([set(futurs)] if g.nom != "vitale" and set(futurs) != jours else [])
        for jours in essais:
            reponses = self.diffuser(AgentSalle, "CFP", "cfp_urgence",
                                     {"patient": p, "chirurgiens": c["chirurgiens"], "t_min": t_min, "limite": limite,
                                      "jours": jours, "maintenant": maintenant, "fenetres": fenetres, "ctx": ctx},
                                     conv, f"P{p.id} {p.duree_bloc} min, au plus tôt {hm(t_min)}"
                                     + ("" if jours is essais[0] else " (horizon élargi)"))
            props = [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]]
            choix = self._choisir(props, conv, lambda pl: (pl.hors_delai, pl.cout))
            if choix is not None:
                break
        if choix is not None and g.nom == "vitale" and choix[1].hors_delai:
            choix = None                                    # une urgence vitale hors délai est transférée
        if choix is None:
            alerte = (f"URGENCE {g.nom} P{p.id} : aucun créneau du planning dans le délai -> transfert vers un autre établissement"
                      if g.nom == "vitale" else f"URGENCE P{p.id} : aucun créneau du planning ne convient -> transfert vers un autre établissement")
            self.alertes.append(alerte)
            self.annoncer(f"  ⚠ {alerte}")
            self.decisions = [d for d in self.decisions if not (d["type"] == "urgence" and d["patient"] == p.id)]
            self.decisions.append({"type": "urgence_refusee", "heure": maintenant, "patient": p.id})
            return False, {"motif": alerte}, alerte
        agent, plan, extra, note = choix
        retirees = self._appliquer(agent, plan, props, conv)
        nouvelle = plan.ajouts[0]
        attente = minutes(plan.debut_urgence - c["arrivee"])
        self.annoncer(f"  ✔ {'Nouvelle décision' if reinsertion else 'Décision'} : P{p.id} opéré(e) par {self.model.nom_chir(nouvelle.chirurgien_id)} en "
                      f"{self.model.annuaire[agent].nom_affiche} à {hm(plan.debut_urgence)} le {jour_txt(plan.jour)} "
                      f"(attente {attente:.0f} min, {len(props)} propositions reçues, coût {plan.cout + extra:,.0f})")
        self.annoncer(f"    {plan.resume}")
        if note:
            self.annoncer(f"    Contraintes signalées : {note}")
            if "hors capacité" in note:
                alerte = f"P{p.id} : aucun lit libre ({note}) -> la cellule de gestion des lits doit trouver un lit d'aval"
                self.alertes.append(alerte)
                self.annoncer(f"  ⚠ {alerte}")
        if plan.hors_delai:
            alerte = (f"URGENCE {g.nom} P{p.id} : délai de {g.delai_max_min} min dépassé ({attente:.0f} min) "
                      f"-> prévenir le médecin régulateur (transfert vers un autre établissement ?)")
            self.alertes.append(alerte)
            self.annoncer(f"  ⚠ {alerte}")
        # une ré-insertion remplace la décision précédente (le bilan ne compte qu'une urgence)
        self.decisions = [d for d in self.decisions if not (d["type"] == "urgence" and d["patient"] == p.id)]
        self.decisions.append({"type": "urgence", "heure": maintenant, "patient": p.id, "gravite": g.nom,
                               "salle": plan.salle_id, "chirurgien": nouvelle.chirurgien_id,
                               "debut": plan.debut_urgence, "attente_min": attente, "dans_delai": not plan.hors_delai,
                               "cout": plan.cout + extra, "detail": plan.detail, "plan": plan.resume,
                               "nb_propositions": len(props), "reprogrammee": reinsertion})
        self._replacer(retirees, conv)
        return True, {"plan": plan}, plan.resume

    # ---------- panne
    def sur_transferts_bloques(self, msg: Message):
        conv, fenetres = msg.conversation, msg.contenu["fenetres"]
        reponses = self.diffuser(AgentSalle, "CFP", "cfp_panne", {"fenetres": fenetres, "maintenant": self.maintenant},
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

    def sur_transferts_retablis(self, msg: Message):
        conv = msg.conversation
        reponses = self.diffuser(AgentSalle, "CFP", "cfp_compacter",
                                 {"fenetres": msg.contenu["fenetres"], "maintenant": self.maintenant},
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
            reponses = self.diffuser(AgentSalle, "CFP", "cfp_replacement",
                                     {"intervention": it, "apres": debut, "fenetres": self._fenetres(conv),
                                      "chirurgiens": self.competents(it), "jour_reference": jour_ref},
                                     conv, f"replacer P{it.pid} ({it.patient.duree_bloc} min)")
            props = [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]]
            choix = self._choisir(props, conv, lambda pl: (False, pl.cout))
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
            self._relancer_attente(self.model.nouvelle_conversation("ATT"), t)


# =============================================================================
# 6. LE MODÈLE MESA
# =============================================================================

class BlocOperatoire(mesa.Model):
    """Modèle Mesa : horloge, événements, acheminement des messages, collecte des indicateurs."""

    def __init__(self, instance1: InstanceProbleme, instance2: InstanceNiveau2, solution: SolutionPatients,
                 specialites: Optional[dict[int, str]] = None, chirurgien_garde: Optional[int] = None,
                 parametres: ParametresSMA = ParametresSMA(), batiment: Batiment = Batiment(),
                 verbeux: int = 1, seed: Optional[int] = 42):
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
        self.chirurgiens = {}
        for cid, c in instance1.chirurgiens.items():
            dispo = instance1.disponibilites_chirurgiens.get(cid)
            jours = {instance1.creneaux[k].jour for k in dispo} if dispo else set(self.jours_planning)
            self.chirurgiens[cid] = AgentChirurgien(self, cid, c.nom, jours)

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
    def depuis_v28(cls, lundi: date, nb_semaines: int = 2, solution: Optional[SolutionPatients] = None,
                   instances: Optional[tuple[InstanceProbleme, InstanceNiveau2]] = None, **kw) -> "BlocOperatoire":
        """Planning réel planning_vacations_v28 à partir de `lundi` (parité déduite de la date).
        `solution` : affectation N2 de vos métaheuristiques / de l'hybridation, calculée sur
        `instances` (sinon : glouton multi-départ commun). Les plages URGENCE sont tenues par le
        « chirurgien d'urgence » anonyme (id 900)."""
        i1, i2 = instances or construire_instances_v28(lundi, nb_semaines)
        kw.setdefault("specialites", specialites_par_id())
        kw.setdefault("chirurgien_garde", ID_CHIR_URGENCE)
        return cls(i1, i2, solution or construire_meilleure_affectation_initiale(i2), **kw)

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
        return self.chirurgiens[cid].nom_affiche if cid in self.chirurgiens else f"chir {cid}"

    def _declencher(self, evt: Evenement):
        t = evt.heure
        if isinstance(evt, ArriveeUrgence):
            conv = self.nouvelle_conversation("URG")
            p = evt.patient
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
        return {
            "evenements": len(self.evenements),
            "urgences_inserees": len(urg),
            "urgences_dans_delai": sum(d["dans_delai"] for d in urg),
            "urgences_refusees": sum(d["type"] == "urgence_refusee" for d in self.regulation.decisions),
            "attente_moyenne_urgence_min": round(sum(d["attente_min"] for d in urg) / len(urg), 1) if urg else 0.0,
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
        }

    def afficher_bilan(self):
        b = self.bilan()
        print(f"\n  {'═' * 92}\n  BILAN DU SYSTÈME MULTI-AGENT\n  {'═' * 92}")
        print(f"  Événements traités                 : {b['evenements']}")
        print(f"  Urgences insérées                  : {b['urgences_inserees']} (dont {b['urgences_dans_delai']} dans le "
              f"délai, {b['urgences_refusees']} refusée(s)), attente moyenne {b['attente_moyenne_urgence_min']} min")
        print(f"  Patients décalés / avancés         : {b['patients_decales']} / {b['patients_avances']} "
              f"({b['minutes_de_decalage_cumulees']} min cumulées)")
        print(f"  Patients reportés à un autre jour  : {b['patients_reportes_autre_jour']}")
        print(f"  Patients repris par un confrère    : {b['patients_repris_par_un_confrere']}")
        print(f"  Patients en liste d'attente        : {b['patients_en_liste_attente']}")
        print(f"  Contrôle de cohérence              : {'OK' if not b['erreurs_de_coherence'] else str(b['erreurs_de_coherence']) + ' erreur(s)'}"
              f" (salles, chirurgiens, heures du planning, agendas, séjours)")
        print(f"  Messages échangés                  : {b['messages_echanges']}  {b['messages_par_performatif']}")
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
        if {i.pid: i.debut.date() for i in its} != {pid: j for pid, (_, j) in self.hebergement.sejours.items()}:
            erreurs.append("séjours de l'hébergement désynchronisés")
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
        salles = list(self.salles.values())
        du_jour = sorted({it.chirurgien_id for s in salles for it in s.du_jour(jour)}
                         | {f.chirurgien_id for s in salles for f in s.creneaux.values()
                            if f.jour == jour and not f.urgence})
        couleur = {cid: palette[k % len(palette)] for k, cid in enumerate(du_jour)}   # couleurs des praticiens du jour
        fig, ax = plt.subplots(figsize=(13, 1.1 * len(salles) + 1.6))
        x = lambda t: t.hour + t.minute / 60
        if panne:
            ax.axvspan(x(panne[0]), x(panne[1]), color="#b0b0b0", alpha=0.25, lw=0)
            ax.text(x(panne[0]) + 0.05, -0.6, "monte-lit en panne", fontsize=8, color="#555")
        for k, s in enumerate(salles):
            y = len(salles) - 1 - k
            for f in s.creneaux.values():
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
        ax.set_xlim(7.5, 17.5)
        ax.set_xticks(range(8, 18))
        ax.set_xticklabels([f"{h}h" for h in range(8, 18)])
        for cote in ("top", "right", "left"):
            ax.spines[cote].set_visible(False)
        ax.grid(axis="x", color="#e4e3df")
        ax.set_axisbelow(True)
        ax.set_title(titre or jour_txt(jour), loc="left", fontsize=11)
        chirs = sorted({it.chirurgien_id for s in salles for it in s.du_jour(jour)}
                       | {f.chirurgien_id for s in salles for f in s.creneaux.values() if f.jour == jour and not f.urgence})
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
