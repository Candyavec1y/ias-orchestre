# -*- coding: utf-8 -*-
"""
hybridation.py
==============

Hybridation des TROIS métaheuristiques du projet : ALGORITHME GÉNÉTIQUE SIMPLE (AGS)
+ RECUIT SIMULÉ (RS) + RECHERCHE TABOUE (TABOU), niveaux 1 et 2.

Rôle de chacune :
    AGS    diversification : population, croisement PAR CHIRURGIEN qui recombine les
           meilleurs plannings partiels de solutions différentes ;
    RS     exploration : accepte des dégradations pour franchir les paliers du score ;
    TABOU  intensification : meilleur voisin + mémoire taboue pour vider un bassin.

S'appuie UNIQUEMENT sur structures_communes.py et sorties.py : même fonction objectif pour les modes
hybrides et pour les références RS / Tabou / AGS seuls, résultats au format commun de sorties.py.
C'est la SEULE implémentation de chaque algorithme dans le dépôt (le SMA l'utilise aussi).

Organisation
------------
    0. PARAMÈTRES             ParametresHybride, ParametresRechercheLocale (RS + Tabou)
    1. OUTILS COMMUNS         Journal (suivi de convergence)
    2. RECHERCHE LOCALE       2.1 recuit simulé, 2.2 recherche taboue,
                              2.3 RechercheLocaleMixte (RS puis Tabou selon la phase)
    3. PROBLÈME NIVEAU 1      codage, opérateurs génétiques, voisinage faisable
    4. PROBLÈME NIVEAU 2      codage, opérateurs génétiques, voisinage incrémental
    5. MOTEUR HYBRIDE         AGS + recherche locale, 3 modes d'hybridation
    6. CAMPAGNE               niveaux 1 puis 2, comparaison, sauvegarde JSON

Modes d'hybridation (même budget de temps pour chacun)
------------------------------------------------------
    "memetique"     AGS ; les meilleurs enfants sont polis par le Tabou ; intensification
                    finale RS puis Tabou.
    "AGS>RS>TABOU"  AGS pur (50 % du temps), puis RS puis Tabou sur le meilleur individu.
    "RS>AGS>TABOU"  4 RL de départ (RS puis Tabou) depuis des points différents, AGS
                    mémétique ensemencé par ces optima, intensification finale RS puis Tabou.
    + références : "AGS seul", "RS seul", "TABOU seul" (même budget).
Résultat principal : resultats/<jeu>/AGS+RS+TABOU_n<k>.json ; le reste dans variantes/.

Utilisation
-----------
    python metaheuristiques/hybridation.py                 # instance d'étude, BUDGET_OPTIMISATION_S par mode
    python metaheuristiques/hybridation.py --temps 10
    from hybridation import executer_campagne              # depuis un autre script
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time as chrono
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Callable, Optional

try:                                     # script : dossier du fichier ; notebook : dossier courant
    _DOSSIER = Path(__file__).resolve().parent
except NameError:
    _DOSSIER = Path.cwd()
sys.path.insert(0, str(_DOSSIER))
if str(_DOSSIER.parent / "commun") not in sys.path:   # structures_communes.py partagé : dossier commun/
    sys.path.insert(0, str(_DOSSIER.parent / "commun"))
from parametres import BUDGET_OPTIMISATION_S, GRAINE_POPULATION_N1, NB_SEMAINES_REPORT  # noqa: E402
from structures_communes import (  # noqa: E402
    GRAINE_ETUDE, JOURS_FR, EtatNiveau2, InstanceNiveau2, InstanceProbleme, Individu, ParametresAGS,
    ProblemeGenetique, SolutionPatients, SolutionPlanning, calculer_occupation_par_jour,
    construire_affectation_initiale,
    construire_instance_niveau2, construire_meilleure_affectation_initiale, evaluer_niveau2,
    evaluer_planning, generer_solution_initiale_niveau1, instance_niveau2_reference,
    plages_possibles_pour_chirurgien, vacations_compatibles,
)
from sorties import (  # noqa: E402
    ResultatMetaheuristique, SuiviExecution, afficher_planning, resultat_niveau1, resultat_niveau2,
)

def plages_possibles_pour_bloc(instance, bloc_id):
    """Domaine d'un bloc N1 : les plages possibles de son chirurgien."""
    return plages_possibles_pour_chirurgien(instance, instance.blocs_a_placer[bloc_id].chirurgien_id)


NOM_ALGO = "AGS+RS+TABOU"
NOM_RL = "RS>TABOU"
MODES = ("memetique", "AGS>RS>TABOU", "RS>AGS>TABOU")
REFERENCES = ("AGS seul", "RS seul", "TABOU seul")


# =============================================================================
# 0. PARAMÈTRES
# =============================================================================

@dataclass(frozen=True)
class ParametresRechercheLocale:
    """Paramètres des DEUX recherches locales (RS et Tabou) et de leur enchaînement."""
    # --- recuit simulé (exploration) ---
    acceptation_initiale: float = 0.30        # T0 calibré pour accepter ~30 % des dégradations typiques
    ratio_temperature_finale: float = 1e-3     # T_fin = T0 x ratio (refroidissement géométrique)
    temperature_initiale: Optional[float] = None   # imposée si renseignée (sinon calibrage automatique)
    acceptation_enfant: float = 0.02           # (RS appliqué à un enfant : froid)
    acceptation_finale: float = 0.10           # RS de l'intensification finale : tiède
    # --- recherche taboue (intensification) ---
    taille_tabou: int = 25                     # durée taboue de base (itérations)
    taille_tabou_alea: int = 5                 # durée taboue += randint(0, alea)
    patience: int = 40                         # itérations sans amélioration avant perturbation
    voisins_n1: int = 150                      # N1 : taille du voisinage échantillonné
    voisins_n1_enfant: int = 60                # N1 : voisinage réduit pour le polissage des enfants
    echanges_n2: int = 300                     # N2 : paires (même chirurgien) testées par itération
    ejections_n2: int = 80                     # N2 : insertions avec éjection testées par itération
    force_perturbation_n1: tuple[int, int] = (2, 5)    # N1 : nb de mouvements aléatoires d'une perturbation
    force_perturbation: tuple[int, int] = (15, 30)     # N2 : nb de mouvements aléatoires d'une perturbation
    # --- enchaînement RS -> Tabou ---
    iterations_par_enfant: int = 15            # budget TABOU appliqué à un enfant (mode mémétique)
    part_rs_depart: float = 0.70               # RL de départ : 70 % RS puis 30 % Tabou
    part_rs_finale: float = 0.50               # intensification finale : 50 % RS puis 50 % Tabou


@dataclass(frozen=True)
class ParametresHybride:
    mode: str = "memetique"                    # un de MODES ou de REFERENCES
    ags: ParametresAGS = ParametresAGS(taille_population=30, generations=100_000, taux_croisement=0.9,
                                       taux_mutation=0.4, taille_tournoi=3, elites=2)
    rl: ParametresRechercheLocale = ParametresRechercheLocale()
    temps_max_s: float = BUDGET_OPTIMISATION_S
    individus_ameliores: int = 2               # enfants passés à la recherche locale à chaque génération
    part_finale: float = 0.25                  # part du temps réservée à l'intensification finale
    part_rl_initiale: float = 0.40             # mode "RS>AGS>TABOU" : part du temps des RL de départ
    departs_rl: int = 4                        # mode "RS>AGS>TABOU" : nombre de RL courtes (départs différents)
    graine: int = GRAINE_ETUDE

    @staticmethod
    def pour_mode(mode: str, temps_max_s: float, graine: int = GRAINE_ETUDE, **kw) -> "ParametresHybride":
        p = ParametresHybride(mode=mode, temps_max_s=temps_max_s, graine=graine, **kw)
        if mode == "AGS>RS>TABOU":
            return replace(p, individus_ameliores=0, part_finale=0.50)
        if mode == "AGS seul":
            return replace(p, individus_ameliores=0, part_finale=0.0)
        return p


# =============================================================================
# 1. OUTILS COMMUNS
# =============================================================================

class Journal:
    """Relie toutes les évaluations (AGS + recherche locale) à UN SuiviExecution."""

    def __init__(self, suivi: SuiviExecution):
        self.suivi = suivi
        self.it = 0
        self.meilleur = float("inf")

    def noter(self, courant: float, meilleur_local: Optional[float] = None, evaluations: int = 1):
        self.it += 1
        self.suivi.compter_evaluation(evaluations)
        self.meilleur = min(self.meilleur, courant if meilleur_local is None else meilleur_local)
        self.suivi.enregistrer(self.it, courant, self.meilleur)


# =============================================================================
# 2.1 RECHERCHE LOCALE : RECUIT SIMULÉ (exploration)
# =============================================================================
# Même interface pour les deux niveaux et les deux méthodes :
#     rl(individu, rng, iterations=None, duree=None, phase="depart") -> (individu amélioré, coût)
# phase : "depart" (RL autonome), "enfant" (polissage d'un enfant de l'AGS), "finale" (intensification).

def _temperature(t0: float, ratio: float, progression: float) -> float:
    return t0 * ratio ** min(1.0, max(0.0, progression))


def _calibrer_t0(deltas: list[float], acceptation: float) -> float:
    """T0 tel qu'une dégradation médiane soit acceptée avec la probabilité `acceptation`."""
    positifs = sorted(d for d in deltas if d > 1e-9)
    if not positifs:
        return 1.0
    mediane = positifs[len(positifs) // 2]
    return -mediane / math.log(acceptation)


# =============================================================================
# 2. RECHERCHE LOCALE : RECUIT SIMULÉ
# =============================================================================
# Même interface pour les deux niveaux :
#     rl(individu, rng, iterations=None, duree=None, phase="depart") -> (individu amélioré, coût)
# phase : "depart" (RL autonome), "enfant" (polissage d'un enfant de l'AGS), "finale" (intensification).
# Arrêt à `iterations` OU à `duree` secondes ; refroidissement géométrique indexé sur la
# progression (itérations ou temps), donc la même loi quel que soit le budget.

def recuit_niveau1(pb: "ProblemeHybrideN1", individu: Individu, rng: random.Random,
                   iterations: Optional[int] = None, duree: Optional[float] = None,
                   p: ParametresRechercheLocale = ParametresRechercheLocale(),
                   phase: str = "depart") -> tuple[Individu, float]:
    cur = list(individu)
    occ, occ_c = pb.occupations(cur)
    s = pb.cout(cur)
    meilleur, s_meilleur = list(cur), s

    if p.temperature_initiale:
        t0 = p.temperature_initiale
    else:                                   # calibrage : quelques mouvements testés puis annulés
        deltas = []
        for _ in range(60):
            mv = pb.proposer_mouvement(cur, occ, occ_c, rng)
            if mv:
                pb.appliquer(cur, occ, occ_c, mv)
                deltas.append(pb.cout(cur) - s)
                pb.appliquer(cur, occ, occ_c, pb.inverse(mv))
        t0 = _calibrer_t0(deltas, {"enfant": p.acceptation_enfant, "finale": p.acceptation_finale}.get(
            phase, p.acceptation_initiale))

    debut, it = chrono.perf_counter(), 0
    while True:
        if iterations is not None and it >= iterations:
            break
        ecoule = chrono.perf_counter() - debut
        if duree is not None and ecoule >= duree:
            break
        it += 1
        T = _temperature(t0, p.ratio_temperature_finale, it / iterations if iterations else ecoule / duree)
        mv = pb.proposer_mouvement(cur, occ, occ_c, rng)
        if mv is None:
            continue
        pb.appliquer(cur, occ, occ_c, mv)
        s2 = pb.cout(cur)
        d = s2 - s
        if d <= 0 or rng.random() < math.exp(-d / T):
            s = s2
            if s < s_meilleur:
                meilleur, s_meilleur = list(cur), s
        else:
            pb.appliquer(cur, occ, occ_c, pb.inverse(mv))
        pb.journal.noter(s, s_meilleur, evaluations=0)   # (évaluations comptées par pb.cout)
    return meilleur, s_meilleur


def recuit_niveau2(pb: "ProblemeHybrideN2", individu: Individu, rng: random.Random,
                   iterations: Optional[int] = None, duree: Optional[float] = None,
                   p: ParametresRechercheLocale = ParametresRechercheLocale(),
                   phase: str = "depart") -> tuple[Individu, float]:
    etat = pb.etat(individu)                # évaluation INCRÉMENTALE (EtatNiveau2 commun)
    s = etat.score()
    meilleur, s_meilleur = pb.depuis_etat(etat), s

    if p.temperature_initiale:
        t0 = p.temperature_initiale
    else:
        deltas = []
        for _ in range(150):
            mv = pb.proposer_mouvement(etat, rng)
            if mv:
                pb.appliquer(etat, mv)
                deltas.append(etat.score() - s)
                pb.appliquer(etat, pb.inverse(mv))
        t0 = _calibrer_t0(deltas, {"enfant": p.acceptation_enfant, "finale": p.acceptation_finale}.get(
            phase, p.acceptation_initiale))

    debut, it = chrono.perf_counter(), 0
    while True:
        if iterations is not None and it >= iterations:
            break
        ecoule = chrono.perf_counter() - debut
        if duree is not None and ecoule >= duree:
            break
        it += 1
        T = _temperature(t0, p.ratio_temperature_finale, it / iterations if iterations else ecoule / duree)
        mv = pb.proposer_mouvement(etat, rng)
        if mv is None:
            continue
        pb.appliquer(etat, mv)
        s2 = etat.score()
        d = s2 - s
        if d <= 0 or rng.random() < math.exp(-d / T):
            s = s2
            if s < s_meilleur - 1e-9:
                meilleur, s_meilleur = pb.depuis_etat(etat), s
        else:
            pb.appliquer(etat, pb.inverse(mv))
        pb.journal.noter(s, s_meilleur)
    return meilleur, s_meilleur


# =============================================================================
# 2.2 RECHERCHE LOCALE : RECHERCHE TABOUE (intensification)
# =============================================================================
# Même interface pour les deux niveaux :
#     rl(individu, rng, iterations=None, duree=None, phase="depart") -> (individu amélioré, coût)
# phase : "depart" (RL autonome), "enfant" (polissage d'un enfant de l'AGS), "finale" (intensification).
# À chaque itération : meilleur voisin NON TABOU (critère d'aspiration : un mouvement tabou est
# accepté s'il bat le meilleur score connu) ; l'attribut tabou est (élément, ancienne valeur) :
# on interdit de RAMENER un bloc / patient là où il était pendant `taille_tabou` (+ aléa) itérations.
# Stagnation (`patience` itérations sans amélioration) : on repart du meilleur, légèrement perturbé.

EPS = 1e-9


def _duree_taboue(p: ParametresRechercheLocale, rng: random.Random) -> int:
    return p.taille_tabou + rng.randint(0, p.taille_tabou_alea)


def _choisir(candidats_evalues, tabou: dict, it: int, s_meilleur: float, rng: random.Random):
    """Meilleur mouvement admissible (non tabou, ou tabou mais aspirant) ; égalités tirées au sort."""
    best, s_best, egaux = None, float("inf"), 0
    for mv, s2 in candidats_evalues:
        if any(tabou.get((x, new), 0) >= it for x, _, new in mv) and s2 >= s_meilleur - EPS:
            continue
        if s2 < s_best - EPS:
            best, s_best, egaux = mv, s2, 1
        elif abs(s2 - s_best) <= EPS:
            egaux += 1
            if rng.random() < 1.0 / egaux:
                best = mv
    return best, s_best


def tabou_niveau1(pb: "ProblemeHybrideN1", individu: Individu, rng: random.Random,
                  iterations: Optional[int] = None, duree: Optional[float] = None,
                  p: ParametresRechercheLocale = ParametresRechercheLocale(),
                  phase: str = "depart") -> tuple[Individu, float]:
    cur = list(individu)
    occ, occ_c = pb.occupations(cur)
    s = pb.cout(cur)
    meilleur, s_meilleur = list(cur), s
    tabou: dict = {}
    nb_voisins = p.voisins_n1_enfant if phase == "enfant" else p.voisins_n1
    debut, it, derniere_amelioration = chrono.perf_counter(), 0, 0
    while True:
        if iterations is not None and it >= iterations:
            break
        if duree is not None and chrono.perf_counter() - debut >= duree:
            break
        it += 1
        # voisinage échantillonné (déplacements / échanges faisables, biais de compactage)
        vus, evalues = set(), []
        for _ in range(nb_voisins):
            mv = pb.proposer_mouvement(cur, occ, occ_c, rng)
            if mv is None or mv in vus:
                continue
            vus.add(mv)
            pb.appliquer(cur, occ, occ_c, mv)
            evalues.append((mv, pb.cout(cur)))
            pb.appliquer(cur, occ, occ_c, pb.inverse(mv))
        mv, s2 = _choisir(evalues, tabou, it, s_meilleur, rng)
        if mv is None:
            tabou.clear()
            continue
        pb.appliquer(cur, occ, occ_c, mv)
        s = s2
        for i, old, _ in mv:
            tabou[(i, old)] = it + _duree_taboue(p, rng)
        if s < s_meilleur - EPS:
            meilleur, s_meilleur, derniere_amelioration = list(cur), s, it
        elif it - derniere_amelioration >= p.patience:          # perturbation depuis le meilleur
            cur = list(meilleur)
            occ, occ_c = pb.occupations(cur)
            for _ in range(rng.randint(*p.force_perturbation_n1)):
                m = pb.proposer_mouvement(cur, occ, occ_c, rng)
                if m:
                    pb.appliquer(cur, occ, occ_c, m)
            s = pb.cout(cur)
            tabou.clear()
            derniere_amelioration = it
        pb.journal.noter(s, s_meilleur, evaluations=0)   # (évaluations comptées par pb.cout)
    return meilleur, s_meilleur


def voisinage_niveau2(pb: "ProblemeHybrideN2", etat: EtatNiveau2, rng: random.Random,
                      p: ParametresRechercheLocale) -> list:
    """Voisinage N2 : TOUS les déplacements + un échantillon d'échanges (même chirurgien)
    + un échantillon d'insertions avec éjection (cf. ProblemeHybrideN2._insertion_ejection)."""
    aff, mvs = etat.aff, []
    for i, pid in enumerate(pb.pids):
        old = aff[pid]
        for v in pb.compat[i]:
            if v != old:
                mvs.append(((pid, old, v),))
    if not hasattr(pb, "_paires"):
        pb._paires = [(a, b) for idx in pb.indices_par_chir.values()
                      for k, a in enumerate(idx) for b in idx[k + 1:]]
    paires = pb._paires if len(pb._paires) <= p.echanges_n2 else rng.sample(pb._paires, p.echanges_n2)
    for a, b in paires:
        pa, pb_ = pb.pids[a], pb.pids[b]
        va, vb = aff[pa], aff[pb_]
        if va != vb:
            mvs.append(((pa, va, vb), (pb_, vb, va)))
    non_places = [i for i in range(pb.n) if aff[pb.pids[i]] is None and pb.compat[i]]
    for _ in range(p.ejections_n2):
        i = rng.choice(non_places) if non_places and rng.random() < 0.5 else rng.randrange(pb.n)
        mv = pb._insertion_ejection(etat, i, rng) if pb.compat[i] else None
        if mv:
            mvs.append(mv)
    return mvs


def tabou_niveau2(pb: "ProblemeHybrideN2", individu: Individu, rng: random.Random,
                  iterations: Optional[int] = None, duree: Optional[float] = None,
                  p: ParametresRechercheLocale = ParametresRechercheLocale(),
                  phase: str = "depart") -> tuple[Individu, float]:
    etat = pb.etat(individu)                # évaluation INCRÉMENTALE (EtatNiveau2 commun)
    s = etat.score()
    meilleur, s_meilleur = pb.depuis_etat(etat), s
    tabou: dict = {}
    debut, it, derniere_amelioration = chrono.perf_counter(), 0, 0
    while True:
        if iterations is not None and it >= iterations:
            break
        if duree is not None and chrono.perf_counter() - debut >= duree:
            break
        it += 1
        evalues = []
        for mv in voisinage_niveau2(pb, etat, rng, p):
            pb.appliquer(etat, mv)
            evalues.append((mv, etat.score()))
            pb.appliquer(etat, pb.inverse(mv))
        pb.journal.suivi.compter_evaluation(len(evalues))
        mv, s2 = _choisir(evalues, tabou, it, s_meilleur, rng)
        if mv is None:
            tabou.clear()
            continue
        pb.appliquer(etat, mv)
        s = s2
        for pid, old, _ in mv:
            if old is not None:
                tabou[(pid, old)] = it + _duree_taboue(p, rng)
        if s < s_meilleur - EPS:
            meilleur, s_meilleur, derniere_amelioration = pb.depuis_etat(etat), s, it
        elif it - derniere_amelioration >= p.patience:          # perturbation depuis le meilleur
            etat = pb.etat(meilleur)
            for _ in range(rng.randint(*p.force_perturbation)):
                m = pb.proposer_mouvement(etat, rng)
                if m:
                    pb.appliquer(etat, m)
            s = etat.score()
            tabou.clear()
            derniere_amelioration = it
        pb.journal.noter(s, s_meilleur, evaluations=0)
    return meilleur, s_meilleur


# =============================================================================
# 2.3 RECHERCHE LOCALE MIXTE : RS (exploration) puis TABOU (intensification)
# =============================================================================
# Le recuit traverse les paliers du paysage (il accepte des dégradations), la recherche
# taboue exploite ensuite à fond le bassin atteint (meilleur voisin, mémoire taboue).
#   phase "depart" : RS sur `part_rs_depart` du temps, puis Tabou depuis le résultat du RS
#   phase "enfant" : Tabou court (polissage d'un enfant de l'AGS, `iterations_par_enfant`)
#   phase "finale" : RS tiède sur `part_rs_finale` du temps, puis Tabou

class RechercheLocaleMixte:
    def __init__(self, niveau: int, pb, p: ParametresRechercheLocale):
        self.pb, self.p = pb, p
        self._rs = recuit_niveau1 if niveau == 1 else recuit_niveau2
        self._tabou = tabou_niveau1 if niveau == 1 else tabou_niveau2

    def rs(self, ind, rng, iterations=None, duree=None, phase="depart"):
        return self._rs(self.pb, ind, rng, iterations, duree, self.p, phase)

    def tabou(self, ind, rng, iterations=None, duree=None, phase="depart"):
        return self._tabou(self.pb, ind, rng, iterations, duree, self.p, phase)

    def __call__(self, ind, rng, iterations=None, duree=None, phase="depart"):
        if phase == "enfant" or duree is None:
            return self.tabou(ind, rng, iterations=iterations or self.p.iterations_par_enfant, phase="enfant")
        part = self.p.part_rs_finale if phase == "finale" else self.p.part_rs_depart
        ind1, c1 = self.rs(ind, rng, duree=duree * part, phase=phase)
        ind2, c2 = self.tabou(ind1, rng, duree=duree * (1 - part), phase=phase)
        return (ind2, c2) if c2 <= c1 else (ind1, c1)


# =============================================================================
# 3. PROBLÈME NIVEAU 1 : chirurgiens -> plages (salle x créneau)
# =============================================================================
# Chromosome : une plage par bloc (blocs triés par id).
# Faisabilité : une plage ne reçoit qu'un bloc ; un chirurgien n'a qu'un bloc par créneau
# (les créneaux forment une grille, deux créneaux se chevauchent <=> même créneau).

class ProblemeHybrideN1(ProblemeGenetique):
    niveau = 1

    def __init__(self, instance: InstanceProbleme, journal: Journal):
        self.inst, self.journal = instance, journal
        self.blocs = sorted(instance.blocs_a_placer)
        self.n = len(self.blocs)
        self.chir = [instance.blocs_a_placer[b].chirurgien_id for b in self.blocs]
        self.dom = [list(plages_possibles_pour_bloc(instance, b)) for b in self.blocs]
        self.dom_set = [set(d) for d in self.dom]
        self.indices_par_chir: dict[int, list[int]] = defaultdict(list)
        for i, c in enumerate(self.chir):
            self.indices_par_chir[c].append(i)
        self.cren = {pid: p.creneau_id for pid, p in instance.plages_bloc.items()}
        self.salle = {pid: p.salle_id for pid, p in instance.plages_bloc.items()}
        # plages ADJACENTES (même salle, même jour, créneau contigu) : sert au compactage
        par_case = {(p.salle_id, p.creneau_id): pid for pid, p in instance.plages_bloc.items()}
        C = instance.creneaux
        contigus = {cid: [c2.id for c2 in C.values() if c2.jour == c.jour
                          and (c2.heure_debut == c.heure_fin or c2.heure_fin == c.heure_debut)]
                    for cid, c in C.items()}
        self.adj = {pid: [par_case[(p.salle_id, c2)] for c2 in contigus[p.creneau_id] if (p.salle_id, c2) in par_case]
                    for pid, p in instance.plages_bloc.items()}
        # plage suivante / précédente dans la même salle (créneau contigu) : segments de vacation
        suiv_cren = {cid: next((c2.id for c2 in C.values() if c2.jour == c.jour and c2.heure_debut == c.heure_fin), None)
                     for cid, c in C.items()}
        self.suivant = {pid: par_case.get((p.salle_id, suiv_cren[p.creneau_id])) for pid, p in instance.plages_bloc.items()}
        self.precedent = {q: pid for pid, q in self.suivant.items() if q is not None}
        self._cache: dict[tuple, float] = {}

    # ---------------- codage / évaluation ----------------
    def vers_solution(self, individu: Individu) -> SolutionPlanning:
        return SolutionPlanning(dict(zip(self.blocs, individu)))

    def depuis_solution(self, solution: SolutionPlanning) -> Individu:
        return [solution.affectations[b] for b in self.blocs]

    def evaluer(self, solution: SolutionPlanning) -> float:
        return evaluer_planning(self.inst, solution).score_total

    def cout(self, individu: Individu) -> float:
        cle = tuple(individu)
        s = self._cache.get(cle)
        if s is None:
            if len(self._cache) > 300_000:
                self._cache.clear()
            s = self._cache[cle] = self.evaluer(self.vers_solution(individu))
            self.journal.suivi.compter_evaluation()
        return s

    def solution_initiale(self, rng: random.Random) -> SolutionPlanning:
        return generer_solution_initiale_niveau1(self.inst, random.Random(GRAINE_ETUDE))

    # ---------------- faisabilité ----------------
    def occupations(self, ind: Individu) -> tuple[dict, dict]:
        occ, occ_c = {}, {}
        for i, pid in enumerate(ind):
            occ[pid] = i
            occ_c[(self.chir[i], self.cren[pid])] = i
        return occ, occ_c

    def reparer(self, ind: Individu, rng: random.Random) -> Individu:
        """Supprime les conflits (salle, chirurgien, domaine) en replaçant les blocs fautifs
        sur une plage libre, de préférence collée à un autre bloc du chirurgien et dans
        une salle qu'il utilise déjà (pour ne pas dégrader compacité / dispersion)."""
        ind = list(ind)
        ordre = list(range(self.n))
        rng.shuffle(ordre)
        occ, occ_c, fautifs = {}, {}, []
        for i in ordre:
            pid, cle = ind[i], (self.chir[i], self.cren[ind[i]])
            if pid in self.dom_set[i] and pid not in occ and cle not in occ_c:
                occ[pid], occ_c[cle] = i, i
            else:
                fautifs.append(i)
        for i in fautifs:
            c = self.chir[i]
            libres = [q for q in self.dom[i] if q not in occ and (c, self.cren[q]) not in occ_c]
            if not libres:
                continue                                    # conflit conservé (pénalisé par le score)
            salles_c = {self.salle[ind[j]] for j in self.indices_par_chir[c] if j != i}

            def cle(q):
                colle = any(occ.get(a) is not None and self.chir[occ[a]] == c for a in self.adj[q])
                return (not colle, self.salle[q] not in salles_c, rng.random())
            q = min(libres, key=cle)
            ind[i] = q
            occ[q], occ_c[(c, self.cren[q])] = i, i
        return ind

    # ---------------- opérateurs génétiques ----------------
    def individu_aleatoire(self, rng: random.Random) -> Individu:
        return self.reparer([rng.choice(d) for d in self.dom], rng)

    def population_initiale(self, rng: random.Random, taille: int, graines: list[Individu]) -> list[Individu]:
        pop = [list(g) for g in graines]
        k = 0
        while len(pop) < min(taille, len(graines) + taille // 3):   # 1/3 : backtracking diversifié
            k += 1
            pop.append(self.depuis_solution(generer_solution_initiale_niveau1(
                self.inst, random.Random(GRAINE_POPULATION_N1 + k))))
        while len(pop) < taille:                                    # reste : aléatoire réparé
            pop.append(self.individu_aleatoire(rng))
        return pop

    def croiser(self, parent1: Individu, parent2: Individu, rng: random.Random) -> tuple[Individu, Individu]:
        """Croisement PAR CHIRURGIEN : l'enfant hérite de tout le planning d'un chirurgien
        chez l'un des parents (préserve les vacations compactes), puis réparation."""
        e1, e2 = list(parent1), list(parent2)
        for idx in self.indices_par_chir.values():
            if rng.random() < 0.5:
                for i in idx:
                    e1[i], e2[i] = parent2[i], parent1[i]
        return self.reparer(e1, rng), self.reparer(e2, rng)

    def muter(self, individu: Individu, rng: random.Random) -> Individu:
        ind = list(individu)
        for _ in range(1 + (rng.random() < 0.3)):
            i = rng.randrange(self.n)
            c = self.chir[i]
            if rng.random() < 0.6:          # rapprocher le bloc d'un autre bloc du même chirurgien
                cands = [a for j in self.indices_par_chir[c] if j != i for a in self.adj[ind[j]]
                         if a in self.dom_set[i]]
                ind[i] = rng.choice(cands) if cands else rng.choice(self.dom[i])
            else:                           # déplacement aléatoire dans le domaine
                ind[i] = rng.choice(self.dom[i])
        return self.reparer(ind, rng)

    # ---------------- voisinage (recherche locale) ----------------
    def _segment(self, cur: Individu, occ: dict, i: int) -> list[int]:
        """Blocs contigus (même chirurgien, même salle, même jour) formant la vacation de i."""
        c, seg = self.chir[i], [i]
        q = self.precedent.get(cur[i])
        while q is not None and occ.get(q) is not None and self.chir[occ[q]] == c:
            seg.insert(0, occ[q])
            q = self.precedent.get(q)
        q = self.suivant.get(cur[i])
        while q is not None and occ.get(q) is not None and self.chir[occ[q]] == c:
            seg.append(occ[q])
            q = self.suivant.get(q)
        return seg

    def _deplacer_segment(self, cur: Individu, occ: dict, occ_c: dict, rng: random.Random):
        """Translate TOUTE une vacation (segment de blocs contigus) vers des plages contiguës libres."""
        seg = self._segment(cur, occ, rng.randrange(self.n))
        if len(seg) < 2:
            return None
        c = self.chir[seg[0]]
        cibles = [rng.choice(self.dom[seg[0]])]
        for _ in seg[1:]:
            q = self.suivant.get(cibles[-1])
            if q is None:
                return None
            cibles.append(q)
        if cibles == [cur[k] for k in seg]:
            return None
        for k, q in zip(seg, cibles):
            o, oc = occ.get(q), occ_c.get((c, self.cren[q]))
            if q not in self.dom_set[k] or (o is not None and o not in seg) or (oc is not None and oc not in seg):
                return None
        return tuple((k, cur[k], q) for k, q in zip(seg, cibles))

    def proposer_mouvement(self, cur: Individu, occ: dict, occ_c: dict, rng: random.Random):
        """Déplacement d'un bloc vers une plage libre, échange de deux blocs, ou translation d'une
        vacation entière ; toujours FAISABLE. La moitié des cibles de déplacement sont collées à un
        bloc du même chirurgien (compactage)."""
        if rng.random() < 0.2:
            for _ in range(5):
                mv = self._deplacer_segment(cur, occ, occ_c, rng)
                if mv:
                    return mv
        for _ in range(10):
            i = rng.randrange(self.n)
            c, old = self.chir[i], cur[i]
            if rng.random() < 0.5:
                cands = [a for j in self.indices_par_chir[c] if j != i for a in self.adj[cur[j]]
                         if a in self.dom_set[i]]
                t = rng.choice(cands) if cands else rng.choice(self.dom[i])
            else:
                t = rng.choice(self.dom[i])
            if t == old:
                continue
            j = occ.get(t)
            if j is None:
                k = occ_c.get((c, self.cren[t]))
                if k is not None and k != i:
                    continue
                return ((i, old, t),)
            if j == i or old not in self.dom_set[j]:
                continue
            c2 = self.chir[j]
            if c != c2:
                k = occ_c.get((c, self.cren[t]))
                k2 = occ_c.get((c2, self.cren[old]))
                if (k is not None and k != i) or (k2 is not None and k2 != j):
                    continue
            return ((i, old, t), (j, t, old))
        return None

    @staticmethod
    def inverse(mv):
        return tuple((i, new, old) for i, old, new in reversed(mv))

    def appliquer(self, cur: Individu, occ: dict, occ_c: dict, mv):
        for i, old, _ in mv:
            if occ.get(old) == i:
                del occ[old]
            cle = (self.chir[i], self.cren[old])
            if occ_c.get(cle) == i:
                del occ_c[cle]
        for i, _, new in mv:
            cur[i] = new
            occ[new] = i
            occ_c[(self.chir[i], self.cren[new])] = i


# =============================================================================
# 4. PROBLÈME NIVEAU 2 : patients -> vacations
# =============================================================================
# Chromosome : une vacation (ou None = non placé) par patient (patients triés par id).
# Évaluation : EtatNiveau2 commun (même score que evaluer_niveau2).

class ProblemeHybrideN2(ProblemeGenetique):
    niveau = 2

    def __init__(self, instance2: InstanceNiveau2, journal: Journal):
        self.inst, self.journal = instance2, journal
        self.pids = sorted(instance2.patients)
        self.n = len(self.pids)
        self.compat = [vacations_compatibles(instance2.patients[p], instance2.vacations) for p in self.pids]
        self.chir = [instance2.patients[p].chirurgien_id for p in self.pids]
        self.indices_par_chir: dict[int, list[int]] = defaultdict(list)
        for i, c in enumerate(self.chir):
            self.indices_par_chir[c].append(i)
        self._cache: dict[tuple, float] = {}

    # ---------------- codage / évaluation ----------------
    def vers_solution(self, individu: Individu) -> SolutionPatients:
        return SolutionPatients(dict(zip(self.pids, individu)))

    def depuis_solution(self, solution: SolutionPatients) -> Individu:
        return [solution.affectations.get(p) for p in self.pids]

    def etat(self, individu: Individu) -> EtatNiveau2:
        return EtatAvecReport(self.inst, dict(zip(self.pids, individu)))

    def depuis_etat(self, etat: EtatNiveau2) -> Individu:
        return [etat.aff[p] for p in self.pids]

    def evaluer(self, solution: SolutionPatients) -> float:
        return evaluer_niveau2(self.inst, solution).score_total

    def cout(self, individu: Individu) -> float:
        cle = tuple(individu)
        s = self._cache.get(cle)
        if s is None:
            if len(self._cache) > 200_000:
                self._cache.clear()
            s = self._cache[cle] = self.etat(individu).score()
            self.journal.suivi.compter_evaluation()
        return s

    def solution_initiale(self, rng: random.Random) -> SolutionPatients:
        """Glouton commun (multi-départ) puis report des patients restants : aucun non placé."""
        ind = self.depuis_solution(construire_meilleure_affectation_initiale(self.inst))
        return self.vers_solution(placer_restants(self, ind))

    # ---------------- opérateurs génétiques ----------------
    def individu_aleatoire(self, rng: random.Random) -> Individu:
        """Glouton best-fit (départages aléatoires) puis quelques déplacements aléatoires."""
        ind = self.depuis_solution(construire_affectation_initiale(self.inst, rng))
        for _ in range(rng.randint(2, max(3, self.n // 8))):
            i = rng.randrange(self.n)
            if self.compat[i]:
                ind[i] = rng.choice(self.compat[i])
        return placer_restants(self, ind)

    def population_initiale(self, rng: random.Random, taille: int, graines: list[Individu]) -> list[Individu]:
        pop = [list(g) for g in graines]
        while len(pop) < taille:
            pop.append(self.individu_aleatoire(rng))
        return pop

    def croiser(self, parent1: Individu, parent2: Individu, rng: random.Random) -> tuple[Individu, Individu]:
        """Croisement PAR CHIRURGIEN : les patients d'un chirurgien ne partagent les vacations
        qu'entre eux ; échanger tout le bloc d'un chirurgien garde des vacations cohérentes."""
        e1, e2 = list(parent1), list(parent2)
        for idx in self.indices_par_chir.values():
            if rng.random() < 0.5:
                for i in idx:
                    e1[i], e2[i] = parent2[i], parent1[i]
        return e1, e2

    def muter(self, individu: Individu, rng: random.Random) -> Individu:
        ind = list(individu)
        for _ in range(1 + (rng.random() < 0.3)):
            i = rng.randrange(self.n)
            if not self.compat[i]:
                continue
            if rng.random() < 0.5:          # déplacement (rarement vers « non placé »)
                ind[i] = rng.choice(self.compat[i])          # jamais « non placé »
            else:                           # échange avec un patient du même chirurgien
                j = rng.choice(self.indices_par_chir[self.chir[i]])
                ind[i], ind[j] = ind[j], ind[i]
        return ind

    # ---------------- voisinage incrémental (recherche locale) ----------------
    def proposer_mouvement(self, etat: EtatNiveau2, rng: random.Random):
        """Trois mouvements :
          * déplacement d'un patient vers une autre vacation compatible (éventuellement un report) ;
          * échange de deux patients du même chirurgien (avec un non-placé = éjection simple) ;
          * INSERTION AVEC ÉJECTION : le patient entre dans une vacation et, pour faire de la
            place, un patient qui sature cette vacation OU le lit / la place d'un des jours
            concernés est déplacé ailleurs ou retiré. Indispensable quand les lits sont le goulot."""
        aff = etat.aff
        for _ in range(10):
            if rng.random() < 0.2:          # biais : réinsérer un patient non placé
                np_ = [i for i in range(self.n) if aff[self.pids[i]] is None and self.compat[i]]
                i = rng.choice(np_) if np_ else rng.randrange(self.n)
            else:
                i = rng.randrange(self.n)
            if not self.compat[i]:
                continue
            pid = self.pids[i]
            old = aff[pid]
            tirage = rng.random()
            if tirage < 0.25:
                mv = self._insertion_ejection(etat, i, rng)
                if mv:
                    return mv
                continue
            if tirage < 0.65:
                new = rng.choice(self.compat[i])             # jamais « non placé » : report possible
                if new == old:
                    continue
                return ((pid, old, new),)
            j = rng.choice(self.indices_par_chir[self.chir[i]])
            pid2 = self.pids[j]
            o2 = aff[pid2]
            if o2 == old:
                continue
            return ((pid, old, o2), (pid2, o2, old))
        return None

    def _insertion_ejection(self, etat: EtatNiveau2, i: int, rng: random.Random):
        aff, pid = etat.aff, self.pids[i]
        old = aff[pid]
        cibles = [v for v in self.compat[i] if v != old]
        if not cibles:
            return None
        v = rng.choice(cibles)
        mv = [(pid, old, v)]
        p = self.inst.patients[pid]
        occupants = []
        if rng.random() < 0.5:              # éjection côté HÉBERGEMENT (jour saturé)
            res = etat.places if p.ambulatoire else etat.lits
            satures = [d for d in etat._jours_de(pid, v) if res.occ.get(d, 0) >= res.cap]
            if satures:
                d = rng.choice(satures)
                occupants = [q for q in range(self.n) if q != i and aff[self.pids[q]] is not None
                             and self.inst.patients[self.pids[q]].ambulatoire == p.ambulatoire
                             and d in etat._jours_de(self.pids[q], aff[self.pids[q]])]
        if not occupants:                   # éjection côté BLOC (même vacation)
            occupants = [q for q in self.indices_par_chir[self.chir[i]] if q != i and aff[self.pids[q]] == v]
        if occupants:
            q = rng.choice(occupants)
            pq = self.pids[q]
            oq = aff[pq]
            autres = [w for w in self.compat[q] if w != oq]
            if not autres:
                return None
            mv.append((pq, oq, rng.choice(autres)))      # l'éjecté est reporté, jamais retiré
        return tuple(mv)

    @staticmethod
    def inverse(mv):
        return tuple((p, new, old) for p, old, new in reversed(mv))

    @staticmethod
    def appliquer(etat: EtatNiveau2, mv):
        for pid, _, new in mv:
            etat.deplacer(pid, new)


# =============================================================================
# 4 bis. REPORT SUR LES SEMAINES SUIVANTES (aucun patient non placé)
# =============================================================================
# Les vacations régulières de la semaine étudiée sont reconduites sur les semaines +1..+K
# (Vacation.supplementaire=True, semaine_decalage=k) : un patient qui ne tient pas cette
# semaine est REPORTÉ au lieu d'être laissé non placé. Le choix « non placé » est retiré de
# tous les opérateurs (mutation, voisinages RS / Tabou, éjection).
# Pour que le report reste un dernier recours, l'optimisation interne ajoute au score commun
# une pénalité de report (comme ags_final) : PENALITE_SEMAINE_REPORT x poids(priorité) x semaines.
# Le score_final sauvegardé reste celui de la fonction objectif COMMUNE (comparable).

# NB_SEMAINES_REPORT (commun/parametres.py) : semaines +1..+K ajoutées APRÈS l'horizon, ouvertes au report
PENALITE_SEMAINE_REPORT = 100.0              # par semaine d'attente, x poids de priorité
POIDS_PRIORITE_REPORT = {1: 1, 2: 2, 3: 3, 4: 5}


def etendre_horizon(instance2: InstanceNiveau2, nb_semaines: int = NB_SEMAINES_REPORT) -> InstanceNiveau2:
    """Instance N2 dont les vacations régulières sont dupliquées sur les semaines +1..+nb_semaines."""
    V = dict(instance2.vacations)
    prochain = max(V, default=0) + 1
    regulieres = sorted((v for v in instance2.vacations.values() if not v.supplementaire), key=lambda v: v.id)
    for k in range(1, nb_semaines + 1):
        for v in regulieres:
            V[prochain] = replace(v, id=prochain, jour=v.jour + timedelta(days=7 * k),
                                  supplementaire=True, semaine_decalage=k)
            prochain += 1
    return InstanceNiveau2(instance2.patients, V, instance2.hebergement, instance2.noms_chirurgiens, instance2.nom)


class EtatAvecReport(EtatNiveau2):
    """EtatNiveau2 commun + pénalité de report tenue à jour de façon incrémentale."""

    def __init__(self, instance2: InstanceNiveau2, affectations: Optional[dict] = None,
                 penalite_semaine: float = PENALITE_SEMAINE_REPORT):
        self.penalite_semaine = penalite_semaine
        self.report = 0.0
        super().__init__(instance2, affectations)

    def _poids(self, pid, vid) -> float:
        if vid is None:
            return 0.0
        prio = POIDS_PRIORITE_REPORT.get(self.patients[pid].priorite, 2)
        return self.penalite_semaine * prio * self.vacations[vid].semaine_decalage

    def deplacer(self, pid: int, nouvelle: Optional[int]):
        ancienne = self.aff[pid]
        if ancienne == nouvelle:
            return
        self.report += self._poids(pid, nouvelle) - self._poids(pid, ancienne)
        super().deplacer(pid, nouvelle)

    def score(self) -> float:
        return super().score() + self.report


def placer_restants(pb: "ProblemeHybrideN2", ind: Individu) -> Individu:
    """Garantie : chaque patient encore non placé va dans la vacation (cette semaine ou une
    semaine suivante) qui dégrade le moins le score -> 0 patient non placé."""
    etat = pb.etat(ind)
    for i, pid in enumerate(pb.pids):
        if etat.aff[pid] is None and pb.compat[i]:
            meilleur, s_min = None, float("inf")
            for v in pb.compat[i]:
                etat.deplacer(pid, v)
                s = etat.score()
                if s < s_min:
                    meilleur, s_min = v, s
            etat.deplacer(pid, meilleur)
    return pb.depuis_etat(etat)


# =============================================================================
# 5. MOTEUR HYBRIDE (générique, identique pour les deux niveaux)
# =============================================================================

RechercheLocale = Callable[..., tuple[Individu, float]]  # ici : RechercheLocaleMixte   # rl(ind, rng, iterations=, duree=, phase=)


class AGSHybride:
    """
    AGS (tournoi, croisement, mutation, élitisme) + recherche locale :
      * à chaque génération, les `individus_ameliores` meilleurs enfants passent par la RL
        (hybridation lamarckienne : le résultat de la RL remplace l'enfant) ;
      * les doublons sont re-mutés (préservation de la diversité) ;
      * à la fin, intensification de la RL sur le meilleur individu (`part_finale` du temps).
    """

    def __init__(self, pb: ProblemeGenetique, p: ParametresHybride, rl: RechercheLocale, journal: Journal):
        self.pb, self.p, self.rl, self.journal = pb, p, rl, journal

    def _tournoi(self, pop, couts, rng):
        k = rng.sample(range(len(pop)), min(self.p.ags.taille_tournoi, len(pop)))
        return pop[min(k, key=couts.__getitem__)]

    def executer(self, population: list[Individu], temps_max: float, rng: random.Random
                 ) -> tuple[Individu, float, int]:
        p, ags, pb = self.p, self.p.ags, self.pb
        t0 = chrono.perf_counter()
        fin_ags = t0 + temps_max * (1 - p.part_finale)
        couts = [pb.cout(x) for x in population]
        ib = min(range(len(population)), key=couts.__getitem__)
        meilleur, c_meilleur = list(population[ib]), couts[ib]
        gen = 0
        while gen < ags.generations and chrono.perf_counter() < fin_ags:
            gen += 1
            ordre = sorted(range(len(population)), key=couts.__getitem__)
            nouvelle = [population[k] for k in ordre[:ags.elites]]
            vus = {tuple(x) for x in nouvelle}
            enfants = []
            while len(nouvelle) + len(enfants) < ags.taille_population:
                p1, p2 = self._tournoi(population, couts, rng), self._tournoi(population, couts, rng)
                e1, e2 = pb.croiser(p1, p2, rng) if rng.random() < ags.taux_croisement else (list(p1), list(p2))
                for e in (e1, e2):
                    if rng.random() < ags.taux_mutation:
                        e = pb.muter(e, rng)
                    essais = 0
                    while tuple(e) in vus and essais < 3:      # doublon -> mutation forcée
                        e, essais = pb.muter(e, rng), essais + 1
                    vus.add(tuple(e))
                    enfants.append(e)
            enfants = enfants[:ags.taille_population - len(nouvelle)]
            ce = [pb.cout(e) for e in enfants]
            if p.individus_ameliores > 0:
                for k in sorted(range(len(enfants)), key=ce.__getitem__)[:p.individus_ameliores]:
                    enfants[k], ce[k] = self.rl(enfants[k], rng, iterations=p.rl.iterations_par_enfant,
                                                phase="enfant")
            population = nouvelle + enfants
            couts = [couts[k] for k in ordre[:ags.elites]] + ce
            ib = min(range(len(population)), key=couts.__getitem__)
            if couts[ib] < c_meilleur:
                meilleur, c_meilleur = list(population[ib]), couts[ib]
            self.journal.noter(couts[ib], c_meilleur, evaluations=0)
        reste = t0 + temps_max - chrono.perf_counter()
        if p.part_finale > 0 and reste > 0.05:
            ind, c = self.rl(meilleur, rng, duree=reste, phase="finale")
            if c < c_meilleur:
                meilleur, c_meilleur = ind, c
        return meilleur, c_meilleur, gen


def resoudre(pb, rl: RechercheLocale, depart: Individu, p: ParametresHybride) -> tuple[Individu, float, dict]:
    """Exécute UN mode d'hybridation (ou une référence) à partir de la solution de départ commune."""
    rng = random.Random(p.graine)
    info = {"mode": p.mode, "generations": 0}
    if p.mode == "RS seul":
        ind, c = rl.rs(depart, rng, duree=p.temps_max_s)
        return ind, c, info
    if p.mode == "TABOU seul":
        ind, c = rl.tabou(depart, rng, duree=p.temps_max_s)
        return ind, c, info
    graines = [depart]
    temps_ags = p.temps_max_s
    if p.mode == "RS>AGS>TABOU":
        # plusieurs recherches locales courtes depuis des départs DIFFÉRENTS : la population
        # initiale contient des optima locaux variés que le croisement par chirurgien recombine
        t_rl = p.temps_max_s * p.part_rl_initiale
        departs = [depart] + [pb.individu_aleatoire(rng) for _ in range(p.departs_rl - 1)]
        graines = [rl(d, rng, duree=t_rl / p.departs_rl)[0] for d in departs] + [depart]
        temps_ags = p.temps_max_s - t_rl
    population = pb.population_initiale(rng, p.ags.taille_population, graines)
    ind, c, gen = AGSHybride(pb, p, rl, pb.journal).executer(population, temps_ags, rng)
    info["generations"] = gen
    return ind, c, info


# =============================================================================
# 6. CAMPAGNE : NIVEAU 1 PUIS NIVEAU 2
# =============================================================================

def _controler_capacite() -> None:
    """Évite qu'une instance N1 impossible (trop de blocs pour les plages libres) fasse
    tourner le backtracking sans fin : lève une ValueError explicite."""
    from structures_communes import construire_instance_etude
    inst = construire_instance_etude()
    libres = [p for p in inst.plages_bloc.values()
              if p.type_plage == "LIBRE" and p.salle_id in inst.salles]
    if len(inst.blocs_a_placer) > len(libres):
        raise ValueError(f"Instance impossible : {len(inst.blocs_a_placer)} blocs de 2 h à placer pour "
                         f"{len(libres)} plages libres. Ajoutez des salles dans structures_communes.py "
                         f"(construire_instance_etude) ou réduisez les besoins horaires.")


def charger_instances(jeu: str) -> tuple[InstanceProbleme, InstanceNiveau2, Callable]:
    """(instance N1, instance N2 de RÉFÉRENCE commune, fabrique d'instance N2 chaînée). Seule l'instance
    d'étude existe ("etude")."""
    if jeu != "etude":
        raise ValueError(f"instance inconnue : {jeu!r} (seule l'instance d'étude « etude » existe)")
    _controler_capacite()                    # échoue vite si l'instance est impossible
    inst1, inst2 = instance_niveau2_reference()
    return inst1, inst2, lambda sol1: construire_instance_niveau2(inst1, sol1, nom="n2_chaine")


def _executer_niveau(niveau: int, instance, modes, temps: float, graine: int,
                     rl_params: ParametresRechercheLocale) -> list[ResultatMetaheuristique]:
    resultats = []
    for mode in modes:
        suivi = SuiviExecution(pas_enregistrement=500)
        journal = Journal(suivi)
        if niveau == 1:
            pb = ProblemeHybrideN1(instance, journal)
            rl = RechercheLocaleMixte(1, pb, rl_params)
            depart_sol = pb.solution_initiale(random.Random(graine))
        else:
            pb = ProblemeHybrideN2(instance, journal)
            rl = RechercheLocaleMixte(2, pb, rl_params)
            depart_sol = pb.solution_initiale(random.Random(graine))
        depart = pb.depuis_solution(depart_sol)
        s0 = pb.evaluer(depart_sol)
        p = ParametresHybride.pour_mode(mode, temps, graine, rl=rl_params)
        with suivi:
            ind, _, info = resoudre(pb, rl, depart, p)
        sol = pb.vers_solution(ind)
        suivi.compteurs["generations"] = info["generations"]
        fabrique = resultat_niveau1 if niveau == 1 else resultat_niveau2
        algo = NOM_ALGO if mode in MODES else mode.split()[0]
        r = fabrique(algo, instance, sol, score_initial=s0, suivi=suivi, parametres=p, graine=graine,
                     variante=mode, notes=f"Hybridation {NOM_ALGO}, mode {mode}")
        print(f"  N{niveau} | {mode:<12} | départ {s0:>11,.1f} -> final {r.score_final:>11,.1f} "
              f"({r.gain_pct:5.1f} %) | {'faisable' if r.faisable else 'NON faisable'} | "
              f"{info['generations']:>5} gén. | {r.temps_calcul_s:5.1f} s")
        resultats.append(r)
    return resultats


def _meilleur_hybride(resultats: list[ResultatMetaheuristique]) -> ResultatMetaheuristique:
    hybrides = [r for r in resultats if r.variante in MODES]
    return min(hybrides, key=lambda r: (not r.faisable if r.niveau == 1 else 0, r.score_final))


# =============================================================================
# 7. AFFICHAGE (format de ags_final : benchmark compact + rapport détaillé)
# =============================================================================

def libelle_jour(jour) -> str:
    return f"{jour.isoformat()} ({JOURS_FR[jour.weekday()].lower()})"


def _reports(r: ResultatMetaheuristique) -> tuple[int, int, int]:
    """(patients reportés, semaines de report cumulées, report pondéré par priorité) d'un résultat N2."""
    nb = tot = pond = 0
    for pid, vid in r.solution.items():
        if vid is None or vid not in r.vacations:
            continue
        k = r.vacations[vid].semaine_decalage
        nb += k > 0
        tot += k
        pond += k * POIDS_PRIORITE_REPORT.get(getattr(r, "_priorites", {}).get(pid, 2), 2)
    return nb, tot, pond


def afficher_benchmark(resultats: list[ResultatMetaheuristique], priorites: Optional[dict] = None) -> None:
    """Tableau comparatif des modes, une ligne par exécution (style ags_final)."""
    if not resultats:
        return
    n1 = resultats[0].niveau == 1
    if n1:
        tete = f"  {'Mode':<16}{'Score':>11}{'Gain %':>8}{'Conflits':>9}{'Salles':>8}{'Fragm.':>8}{'Vac.':>6}{'Faisable':>10}{'Temps(s)':>10}"
    else:
        tete = (f"  {'Mode':<16}{'Score':>11}{'Gain %':>8}{'Non pl.':>9}{'Reportés':>10}{'Rep.pond.':>11}"
                f"{'Dép.bloc':>10}{'Lits+':>7}{'Places+':>9}{'Temps(s)':>10}")
    print(tete + "\n  " + "-" * (len(tete) - 2))
    for r in resultats:
        i = r.indicateurs
        nom = (r.variante or r.algo)[:15]
        if n1:
            print(f"  {nom:<16}{r.score_final:>11,.0f}{r.gain_pct:>8.1f}{i.conflits_salles + i.conflits_chirurgiens:>9}"
                  f"{i.salles_differentes:>8}{i.fragmentation:>8}{i.nb_vacations:>6}{'oui' if r.faisable else 'NON':>10}"
                  f"{r.temps_calcul_s:>10.1f}")
        else:
            r._priorites = priorites or {}
            nb, _, pond = _reports(r)
            print(f"  {nom:<16}{r.score_final:>11,.0f}{r.gain_pct:>8.1f}{i.nb_non_places:>9}{nb:>10}{pond:>11}"
                  f"{i.depassement_bloc_minutes:>10.0f}{i.depassement_lits:>7}{i.depassement_places:>9}"
                  f"{r.temps_calcul_s:>10.1f}")


def afficher_rapport_niveau2(instance2: InstanceNiveau2, solution: SolutionPatients, titre: str,
                             detail: bool = True) -> None:
    """Rapport détaillé N2 (repris de ags_final) : synthèse, vérification indépendante des
    capacités, attente par priorité, puis vacations / jours / patients."""
    V, P = instance2.vacations, instance2.patients
    ev = evaluer_niveau2(instance2, solution)
    aff = solution.affectations
    n = len(P)
    print("\n" + "=" * 110 + f"\n  {titre}\n" + "=" * 110)
    places = [pid for pid, v in aff.items() if v is not None]
    reportes = [pid for pid in places if V[aff[pid]].semaine_decalage > 0]
    sem_tot = sum(V[aff[pid]].semaine_decalage for pid in places)
    pond = sum(V[aff[pid]].semaine_decalage * POIDS_PRIORITE_REPORT.get(P[pid].priorite, 2) for pid in places)
    nb_sem = 1 + max((V[aff[pid]].semaine_decalage for pid in places), default=0)
    print(f"  {n} patients, {nb_sem} semaine(s) effectivement utilisée(s).")
    print(f"\n  Score total (fonction commune) : {ev.score_total:,.1f}")
    print(f"    score blocs                : {ev.score_blocs:,.1f}")
    print(f"    score lits                 : {ev.score_lits:,.1f}")
    print(f"    score places               : {ev.score_places:,.1f}")
    print(f"    patients planifiés         : {len(places)} / {n}")
    print(f"    patients NON planifiés     : {ev.patients_non_places} / {n}")
    print(f"    patients reportés          : {len(reportes)} / {n} (total {sem_tot} semaine(s), "
          f"pondéré par priorité : {pond})")
    print(f"    vacations de report        : {ev.nb_vacations_supp_utilisees} utilisée(s)")
    print(f"    occupation du bloc (sem. 0): {ev.taux_occupation_bloc_pct:.1f} % | temps inoccupé "
          f"{ev.temps_bloc_inoccupe_minutes:.0f} min | dépassement {ev.depassement_bloc_minutes:.0f} min")

    # --- vérification indépendante des capacités (recalculée depuis la solution) ---
    charge: dict[int, float] = {}
    for pid in places:
        charge[aff[pid]] = charge.get(aff[pid], 0.0) + P[pid].duree_bloc
    lits, plc = calculer_occupation_par_jour(instance2, solution)
    h = instance2.hebergement
    t_bloc = max((100 * c / V[v].capacite_utile_minutes for v, c in charge.items()), default=0.0)
    t_lits = max((100 * o / h.cap_lits for o in lits.values()), default=0.0)
    t_plc = max((100 * o / h.cap_places for o in plc.values()), default=0.0)
    ok = max(t_bloc, t_lits, t_plc) <= 100 + 1e-9 and ev.patients_non_places == 0
    print("  Vérification indépendante des capacités :")
    print(f"    remplissage max : bloc {t_bloc:.0f} % de la capacité utile (marge 10 % incluse) | "
          f"lits {t_lits:.0f} % | places {t_plc:.0f} %")
    print(f"    -> {'OK : tous les patients placés, aucune capacité dépassée' if ok else 'ATTENTION : voir dépassements ci-dessus'}")
    print("  Attente moyenne (en semaines) par priorité :")
    for prio in (4, 3, 2, 1):
        s = [V[aff[pid]].semaine_decalage for pid in places if P[pid].priorite == prio]
        if s:
            print(f"    priorité {prio} : {sum(s) / len(s):.2f}  ({len(s)} patients)")
    if not detail:
        return

    par_vac: dict[int, list[int]] = {}
    for pid in places:
        par_vac.setdefault(aff[pid], []).append(pid)
    print("\n  --- Tableau 1 : vacations utilisées (une ligne par vacation et par semaine) ---")
    print(f"  {'Vac':>4} {'Sem':>3} {'Jour':<24} {'Chir.':<7} {'Salle':>5} {'Amb.':>4} {'Hosp.':>5} "
          f"{'Charge':>7} {'Cap.utile':>9} {'Taux':>6}  Type")
    for vid in sorted(par_vac, key=lambda v: (V[v].jour, V[v].heure_debut, V[v].salle_id)):
        v, pats = V[vid], par_vac[vid]
        amb = sum(P[p].ambulatoire for p in pats)
        cap = v.capacite_utile_minutes
        nom = instance2.noms_chirurgiens.get(v.chirurgien_id, str(v.chirurgien_id))
        print(f"  {vid:>4} {v.semaine_decalage:>3} {libelle_jour(v.jour):<24} {nom:<7} {v.salle_id:>5} {amb:>4} "
              f"{len(pats) - amb:>5} {charge[vid]:>7.0f} {cap:>9.0f} {100 * charge[vid] / cap:>5.0f}%  "
              f"{'REPORT' if v.supplementaire else 'RÉG.'}")

    print("\n  --- Tableau 2 : jours occupés (occupation / capacité) ---")
    print(f"  {'Jour':<24} {'Lits occ./cap.':>16} {'Places occ./cap.':>18}")
    for j in sorted(set(lits) | set(plc)):
        print(f"  {libelle_jour(j):<24} {f'{lits.get(j, 0)} / {h.cap_lits}':>16} {f'{plc.get(j, 0)} / {h.cap_places}':>18}")

    print(f"\n  --- Tableau 3 : patients ({n} au total) ---")
    print(f"  {'Patient':>7} {'Nom':<9} {'Type':<5} {'Pr':>2} {'Urg':>3} {'Chir.':<7} {'Vac':>4} {'Salle':>5} "
          f"{'Report':>7} {'Admission':<24} {'Intervention':<24} {'Sortie':<24} {'Bloc':>5}")
    for pid in sorted(P):
        p, vid = P[pid], aff.get(pid)
        nom_c = instance2.noms_chirurgiens.get(p.chirurgien_id, str(p.chirurgien_id))
        debut = (f"  {pid:>7} {p.nom[:9]:<9} {'AMB' if p.ambulatoire else 'HOSP':<5} {p.priorite:>2} "
                 f"{'oui' if p.urgence else '':>3} {nom_c:<7} ")
        if vid is None:
            print(debut + f"{'-':>4} {'-':>5} {'-':>7} NON PLANIFIÉ")
            continue
        v = V[vid]
        adm = v.jour - timedelta(days=0 if p.ambulatoire else p.nuits_pre_op)
        sortie = v.jour + timedelta(days=0 if p.ambulatoire else p.nuits_post_op)
        print(debut + f"{vid:>4} {v.salle_id:>5} {('+' + str(v.semaine_decalage) + ' sem'):>7} "
              f"{libelle_jour(adm):<24} {libelle_jour(v.jour):<24} {libelle_jour(sortie):<24} {p.duree_bloc:>5}")


def executer_campagne(jeu: str = "etude", temps_n1: float = BUDGET_OPTIMISATION_S, temps_n2: float = BUDGET_OPTIMISATION_S,
                      modes=MODES, references: bool = True, dossier: str = "resultats",
                      graine: int = GRAINE_ETUDE, afficher: bool = True,
                      rl_params: ParametresRechercheLocale = ParametresRechercheLocale(),
                      nb_semaines_report: int = NB_SEMAINES_REPORT) -> dict:
    """Niveau 1, niveau 2 (instance de référence commune, avec report possible sur les semaines
    suivantes) puis niveau 2 chaîné sur le planning N1 obtenu."""
    inst1, inst2_base, n2_chainee = charger_instances(jeu)
    inst2 = etendre_horizon(inst2_base, nb_semaines_report)
    tous = list(modes) + (list(REFERENCES) if references else [])
    sortie = Path(dossier) / jeu
    prio = {pid: p.priorite for pid, p in inst2.patients.items()}

    print("=" * 110 + f"\n  {NOM_ALGO} — NIVEAU 1 : planning des vacations ({inst1.nom}, "
          f"{len(inst1.blocs_a_placer)} blocs de 2 h, {temps_n1:.0f} s par mode)\n" + "=" * 110)
    res1 = _executer_niveau(1, inst1, tous, temps_n1, graine, rl_params)
    best1 = _meilleur_hybride(res1)
    print("\n  BENCHMARK NIVEAU 1 (score commun, à minimiser)")
    afficher_benchmark(res1)

    print("\n" + "=" * 110 + f"\n  {NOM_ALGO} — NIVEAU 2 : affectation des patients ({len(inst2.patients)} patients, "
          f"{len(inst2_base.vacations)} vacations + report possible sur {nb_semaines_report} semaine(s), "
          f"{temps_n2:.0f} s par mode)\n" + "=" * 110)
    res2 = _executer_niveau(2, inst2, tous, temps_n2, graine, rl_params)
    best2 = _meilleur_hybride(res2)
    print("\n  BENCHMARK NIVEAU 2 (score commun, à minimiser)")
    afficher_benchmark(res2, prio)

    # Chaînage N1 -> N2 : patients générés sur les vacations du MEILLEUR planning N1 hybride
    inst2c = etendre_horizon(n2_chainee(best1.solution_planning()), nb_semaines_report)
    print("\n" + "=" * 110 + f"\n  {NOM_ALGO} — CHAÎNAGE N1 -> N2 ({len(inst2c.patients)} patients sur le planning N1 "
          f"« {best1.variante} »)\n" + "=" * 110)
    resc = _executer_niveau(2, inst2c, [best2.variante], temps_n2, graine, rl_params)[0]
    resc.variante = f"chaine N1->N2 ({best2.variante})"

    # --- sauvegarde : résultat principal (variante "") + toutes les variantes ---
    for r in res1 + res2 + [resc]:
        nom = r.variante.replace(">", "-").replace(" ", "_").replace("(", "").replace(")", "")
        r.sauvegarder(sortie / "variantes" / f"{r.algo}_{nom}_n{r.niveau}.json")
    for best in (best1, best2):
        principal = ResultatMetaheuristique.from_dict(best.to_dict())
        principal.notes = f"Meilleur mode d'hybridation : {best.variante}"
        principal.variante = ""
        principal.sauvegarder(sortie / f"{NOM_ALGO}_n{best.niveau}.json")

    if afficher:
        print()
        afficher_planning(inst1, best1.solution_planning(),
                          titre=f"PLANNING NIVEAU 1 — {NOM_ALGO}, mode « {best1.variante} »")
        afficher_rapport_niveau2(inst2, best2.solution_patients(),
                                 f"RAPPORT DÉTAILLÉ NIVEAU 2 — {NOM_ALGO}, mode « {best2.variante} »")
        afficher_rapport_niveau2(inst2c, resc.solution_patients(),
                                 f"RAPPORT NIVEAU 2 CHAÎNÉ — {NOM_ALGO}", detail=False)

    print("\n" + "=" * 110 + "\n  SYNTHÈSE\n" + "=" * 110)
    for best, res in ((best1, res1), (best2, res2)):
        refs = {r.variante: r.score_final for r in res if r.variante not in MODES}
        txt = ", ".join(f"{k} {v:,.1f}" for k, v in refs.items())
        print(f"  N{best.niveau} : meilleur mode = {best.variante:<12} score {best.score_final:,.1f} "
              f"(départ commun {best.score_initial:,.1f}, gain {best.gain_pct:.1f} %) | références : {txt}")
    for nom, r in (("N2", best2), ("N2 chaîné", resc)):
        r._priorites = prio if nom == "N2" else {p: q.priorite for p, q in inst2c.patients.items()}
        nb, tot, _ = _reports(r)
        print(f"  {nom:<9} : {r.indicateurs.nb_non_places} patient(s) non placé(s), {nb} reporté(s) "
              f"({tot} semaine(s) au total), score {r.score_final:,.1f}")
    print(f"  -> JSON dans {sortie}/ (principal) et {sortie}/variantes/")
    return {"n1": res1, "n2": res2, "chaine": resc, "meilleur_n1": best1, "meilleur_n2": best2,
            "instance1": inst1, "instance2": inst2, "instance2_chainee": inst2c}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=f"Hybridation {NOM_ALGO} (niveaux 1 et 2).")
    ap.add_argument("--jeu", default="etude", choices=["etude"], help="instance d'étude (niveau 1 et niveau 2)")
    ap.add_argument("--temps", type=float, default=BUDGET_OPTIMISATION_S, help="secondes par mode et par niveau")
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    ap.add_argument("--sans-references", action="store_true", help="ne pas lancer AGS seul / RL seule")
    ap.add_argument("--sortie", default="resultats")
    ap.add_argument("--graine", type=int, default=GRAINE_ETUDE)
    ap.add_argument("--sans-detail", action="store_true", help="ne pas afficher planning et rapport détaillé")
    ap.add_argument("--semaines-report", type=int, default=NB_SEMAINES_REPORT,
                    help="nombre de semaines suivantes ouvertes au report des patients")
    a, _ = ap.parse_known_args()             # ignore les arguments ajoutés par Jupyter / Colab (-f ...)
    executer_campagne(a.jeu, a.temps, a.temps, a.modes, not a.sans_references, a.sortie, a.graine,
                      not a.sans_detail, nb_semaines_report=a.semaines_report)
