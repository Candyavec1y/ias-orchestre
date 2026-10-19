# -*- coding: utf-8 -*-
"""
sma/optimisation_sma.py — Architecture HYBRIDE du SMA : optimisation locale (cas B) + globale (cas A)
=====================================================================================================

Les deux niveaux utilisent VOS métaheuristiques (metaheuristiques/hybridation.py, via
metaheuristiques_sma.optimiser) : RS, Tabou, AGS et les trois modes d'hybridation.

Cas B — ProblemeLocalSalle (dans chaque AgentSalle)
    Quand une salle répond à un appel d'offres (urgence, panne), elle part de son meilleur plan glouton et
    l'améliore par une recherche COURTE : ORDRE DE PASSAGE dans son créneau et choix des patients REPORTÉS.
    Codage : une valeur par patient = son rang de passage, ou REPORTE (-1). Réaction immédiate, en parallèle
    dans chaque salle ; si la recherche ne trouve rien de mieux, le plan glouton est gardé.

Cas A — ProblemeResiduel + AgentOptimisation
    Après chaque aléa, la Régulation demande à l'AgentOptimisation de réoptimiser TOUT le programme restant
    (toutes les salles, tous les jours de l'horizon). Codage identique à votre niveau 2 : une valeur par patient
    = le CRÉNEAU où il est opéré (None = liste d'attente). L'ordre de passage dans chaque créneau est ensuite
    reconstruit par le séquencement du SMA (heure de passage actuelle conservée autant que possible).
    Ne bougent jamais (patients GELÉS) : interventions commencées ou qui commencent dans l'heure (patient déjà
    convoqué), urgences (placées par l'escalade), planning de garde. Le plan n'est appliqué que s'il AMÉLIORE
    le score et s'il est validé par un contrôle GROUPÉ des agents ressources (agendas, lits).

Fonction de coût du cas A (à minimiser) = coûts du SMA + termes lits / places de la fonction N2 commune :
    écart à l'heure initiale (retard / avance x priorité), report à un autre jour (déprogrammation + jours de
    report, x priorité), changement de chirurgien, rétention en salle de réveil (panne), dépassement de la
    capacité utile d'un créneau futur (marge 10 %, poids N2), patient non placé (poids N2), lits / places
    au-delà de la capacité et variance (poids N2), STABILITÉ (chaque patient déplacé coûte un peu).
    Sortir des heures du programme est interdit (pénalité qui écarte le plan).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Optional

from structures_communes import POIDS_N2, PoidsNiveau2, SuiviOccupation, jours_occupation

from metaheuristiques_sma import AGS_GLOBAL, AGS_LOCAL, NOMS, RL_GLOBAL, RL_LOCAL, H, optimiser
from sma_urgences import (MIN, AgentSMA, Fenetre, Intervention, Message, ParametresSMA, Plan, minutes,
                          premier_debut_possible, retention_sspi)

# Pénalités de faisabilité. Elles restent du même ordre que les poids N2 (lit en trop : 5 000) : des valeurs
# démesurées fausseraient le calibrage automatique de la température du recuit (T0 = dégradation médiane).
# Un plan qui en contient une n'est de toute façon JAMAIS appliqué (contrôle final + agents ressources).
PENALITE_HORS_DELAI = 1e7          # cas B : un plan hors délai passe toujours après un plan dans le délai
PENALITE_HORS_HEURES = 20_000      # cas A : sortie des heures du programme (+ 1 000 / min, pour guider la recherche)
PENALITE_LIT_PLAFOND = 15_000      # cas A : lit / place en plus un jour plein (l'agent Hébergement refuserait)
PENALITE_INVALIDE = 1e9            # valeur interdite pour ce patient (créneau incompatible, trop de reports...)
REPORTE = -1


class _ProblemeMoteur(H.ProblemeHybrideN2):
    """Socle commun : ce que le moteur hybride attend d'un problème N2 (pids, compat, groupes, cout...)."""
    niveau = 2

    def _initialiser_moteur(self, pids: list, compat: list[list], groupes: list):
        self.pids, self.n = list(pids), len(pids)
        self.compat = compat
        self.compat_set = [set(c) for c in compat]
        self.chir = groupes                                  # échanges et croisement au sein d'un même groupe
        self.indices_par_chir: dict = defaultdict(list)
        for i, g in enumerate(groupes):
            self.indices_par_chir[g].append(i)
        self._cache: dict = {}
        self.journal = None

    def vers_solution(self, individu):
        return dict(zip(self.pids, individu))

    def depuis_solution(self, solution):
        return [solution.get(p) for p in self.pids]

    def depuis_etat(self, etat):
        return [etat.aff[p] for p in self.pids]

    def evaluer(self, solution) -> float:
        return self.etat(self.depuis_solution(solution)).score()

    def cout(self, individu) -> float:
        cle = tuple(individu)
        s = self._cache.get(cle)
        if s is None:
            if len(self._cache) > 200_000:
                self._cache.clear()
            s = self._cache[cle] = self.etat(individu).score()
            if self.journal is not None:
                self.journal.suivi.compter_evaluation()
        return s

    def solution_initiale(self, rng=None):
        return self.vers_solution(self.individu_courant())

    def individu_aleatoire(self, rng):
        """Individu courant perturbé par quelques déplacements (démarrage à chaud de l'AGS)."""
        ind = list(self.individu_courant())
        for _ in range(rng.randint(2, max(3, self.n // 8))):
            i = rng.randrange(self.n)
            if self.compat[i]:
                ind[i] = rng.choice(self.compat[i])
        return ind

    def _insertion_ejection(self, etat, i, rng):
        """Insertion avec éjection : le patient prend une autre valeur ; un patient qui l'occupait est déplacé."""
        pid, aff = self.pids[i], etat.aff
        old = aff[pid]
        cibles = [v for v in self.compat[i] if v != old]
        if not cibles:
            return None
        v = rng.choice(cibles)
        mv = [(pid, old, v)]
        occupants = [q for q in self.indices_par_chir[self.chir[i]] if q != i and aff[self.pids[q]] == v]
        if occupants:
            q = rng.choice(occupants)
            autres = [w for w in self.compat[q] if w != v]
            if not autres:
                return None
            mv.append((self.pids[q], v, rng.choice(autres)))
        return tuple(mv)


# =============================================================================
# CAS B — optimisation locale dans un agent Salle
# =============================================================================

class _EtatLocal:
    __slots__ = ("pb", "aff")

    def __init__(self, pb: "ProblemeLocalSalle", aff: dict):
        self.pb, self.aff = pb, aff

    def deplacer(self, pid, nouvelle):
        self.aff[pid] = nouvelle

    def score(self) -> float:
        return self.pb._score(tuple(self.aff[p] for p in self.pb.pids))


class ProblemeLocalSalle(_ProblemeMoteur):
    """Ordre de passage + patients reportés dans UN créneau d'une salle."""

    def __init__(self, salle, fen: Fenetre, items: list[Intervention], construire, fenetres: dict, ctx: dict,
                 retirables: set[int], max_retraits: Optional[int], depart: Optional[Plan]):
        self.salle, self.fen, self.construire, self.fenetres, self.ctx = salle, fen, construire, fenetres, ctx
        self.items = {it.pid: it.copie() for it in items}     # copies : l'état de la salle évolue ensuite
        if depart is None:
            ordre, reportes = [it.pid for it in items], set()
        else:
            places = sorted((s, pid) for pid, s in depart.placements.items() if pid in self.items)
            ordre = [pid for _, pid in places] + [it.pid for it in items if it.pid not in depart.placements]
            reportes = set(depart.retraits)
        n = len(ordre)
        self.max_retraits = n if max_retraits is None else max_retraits
        compat = [list(range(n)) + ([REPORTE] if p in retirables and self.max_retraits > 0 else []) for p in ordre]
        self._initialiser_moteur(ordre, compat, [0] * n)
        self._rang = {p: k for k, p in enumerate(ordre)}
        self._depart = [REPORTE if p in reportes else k for k, p in enumerate(ordre)]
        self._plans: dict = {}

    def individu_courant(self):
        return list(self._depart)

    def etat(self, individu):
        return _EtatLocal(self, dict(zip(self.pids, individu)))

    def _decoder(self, valeurs: tuple):
        actifs = sorted((v, self._rang[p], p) for p, v in zip(self.pids, valeurs) if v != REPORTE)
        return [p for _, _, p in actifs], [p for p, v in zip(self.pids, valeurs) if v == REPORTE]

    def plan(self, valeurs) -> Plan:
        valeurs = tuple(valeurs)
        pl = self._plans.get(valeurs)
        if pl is None:
            ordre, ret = self._decoder(valeurs)
            pl = self.salle._evaluer(self.fen, self.construire([self.items[p] for p in ordre]),
                                     [self.items[p] for p in ret], self.fenetres, self.ctx)
            self._plans[valeurs] = pl
        return pl

    def _score(self, valeurs: tuple) -> float:
        pl = self.plan(valeurs)
        trop = max(0, sum(v == REPORTE for v in valeurs) - self.max_retraits)
        # un échange de valeurs peut donner « reporté » à un patient qui ne peut pas l'être (urgence) : interdit
        interdits = sum(v not in ok for v, ok in zip(valeurs, self.compat_set))
        return pl.cout + (PENALITE_HORS_DELAI if pl.hors_delai else 0.0) + (trop + interdits) * PENALITE_INVALIDE

    def valide(self, valeurs) -> bool:
        return self._score(tuple(valeurs)) < PENALITE_INVALIDE

    def individu_aleatoire(self, rng):
        rangs = list(range(self.n))
        rng.shuffle(rangs)
        return rangs


# =============================================================================
# CAS A — problème résiduel global (toutes les salles, tout l'horizon)
# =============================================================================

@dataclass
class Mobile:
    """Patient que l'optimisation globale peut déplacer."""
    it: Intervention                       # état courant (fenetre_id / salle_id = créneau actuel)
    options: list[tuple[int, int]]         # créneaux possibles (salle_id, fenetre_id)
    place: bool                            # True : programmé ; False : en liste d'attente
    jour_reference: date                   # jour initialement prévu (pour le coût de report)

    @property
    def pid(self) -> int:
        return self.it.pid


class _SuiviPlafonne(SuiviOccupation):
    """SuiviOccupation commun + plafond DUR par jour (règle de l'agent Hébergement : pour un patient programmé,
    pas de lit / place en plus un jour où la capacité est atteinte ; le plafond est max(capacité, occupation
    actuelle), car des urgences ont pu la dépasser)."""
    __slots__ = ("plafond", "exces")

    def __init__(self, cap: int, plafond: dict):
        super().__init__(cap)
        self.plafond, self.exces = plafond, 0

    def modifier(self, jours, delta: int):
        occ, cap, pl = self.occ, self.cap, self.plafond
        for j in jours:
            o, lim = occ.get(j, 0), max(cap, pl.get(j, 0))
            self.exces += max(0, o + delta - lim) - max(0, o - lim)
        super().modifier(jours, delta)


class _EtatResiduel:
    """État INCRÉMENTAL du programme résiduel : seuls les créneaux touchés par un mouvement sont re-séquencés,
    lits et places tenus à jour par le SuiviOccupation commun (même convention que EtatNiveau2)."""

    def __init__(self, pb: "ProblemeResiduel", aff: dict):
        self.pb = pb
        self.lits = _SuiviPlafonne(pb.cap_lits, pb.plafond_lits)
        self.places = _SuiviPlafonne(pb.cap_places, pb.plafond_places)
        for jours in pb.jours_fixes_lits:
            self.lits.modifier(jours, +1)
        for jours in pb.jours_fixes_places:
            self.places.modifier(jours, +1)
        self.aff = {p: None for p in pb.pids}
        self.membres: dict[int, set] = defaultdict(set)
        self.cout_creneau: dict[int, float] = {}
        self.sales: set[int] = set()
        self.total_creneaux = 0.0
        self.cout_attente = sum(pb.cout_np[p] for p in pb.pids)
        self.invalides = sum(pb.mobiles[p].place for p in pb.pids)   # programmé -> None : interdit
        for p, v in aff.items():
            self.deplacer(p, v)

    def _jours_de(self, pid, v):
        return self.pb._jours(pid, self.pb.creneaux[self.pb.cles[v]].jour)

    def _invalide(self, pid, v) -> bool:
        pb = self.pb
        return pb.mobiles[pid].place if v is None else v not in pb.compat_set[pb.indice[pid]]

    def deplacer(self, pid, nouvelle):
        ancienne = self.aff[pid]
        if ancienne == nouvelle:
            return
        pb = self.pb
        res = self.places if pb.mobiles[pid].it.patient.ambulatoire else self.lits
        self.invalides -= self._invalide(pid, ancienne)
        if ancienne is None:
            self.cout_attente -= pb.cout_np[pid]
        else:
            self.membres[ancienne].discard(pid)
            self.sales.add(ancienne)
            res.modifier(self._jours_de(pid, ancienne), -1)
        if nouvelle is None:
            self.cout_attente += pb.cout_np[pid]
        else:
            self.membres[nouvelle].add(pid)
            self.sales.add(nouvelle)
            res.modifier(self._jours_de(pid, nouvelle), +1)
        self.invalides += self._invalide(pid, nouvelle)
        self.aff[pid] = nouvelle

    def score(self) -> float:
        pb, w = self.pb, self.pb.w
        for v in self.sales:
            ordre = tuple(sorted(self.membres[v], key=pb.cle.__getitem__))
            c = pb._sequencer(pb.cles[v], ordre)[0] if ordre else 0.0
            self.total_creneaux += c - self.cout_creneau.get(v, 0.0)
            self.cout_creneau[v] = c
        self.sales.clear()
        return (self.total_creneaux + self.cout_attente
                + self.invalides * PENALITE_INVALIDE
                + (self.lits.exces + self.places.exces) * PENALITE_LIT_PLAFOND
                + self.lits.violation * w.lit + self.lits.variance() * w.var_lits
                + self.places.violation * w.place + self.places.variance() * w.var_places)


class ProblemeResiduel(_ProblemeMoteur):
    """
    Individu = un créneau par patient déplaçable (indice dans self.cles), None = liste d'attente.
    Dans chaque créneau, les patients sont séquencés dans l'ordre de leur heure de passage actuelle (heure du jour),
    au plus tôt, autour des patients gelés, en respectant brancardage (pannes), agenda du chirurgien et heures
    du programme.
    """

    def __init__(self, maintenant: datetime, gel: datetime, creneaux: dict[tuple[int, int], Fenetre],
                 fixes: list[Intervention], mobiles: list[Mobile], transferts: dict, cap_lits: int, cap_places: int,
                 parametres: ParametresSMA, poids: PoidsNiveau2 = POIDS_N2):
        self.maintenant, self.gel, self.p, self.w = maintenant, gel, parametres, poids
        self.aujourdhui = maintenant.date()
        self.creneaux, self.transferts = creneaux, transferts
        self.cap_lits, self.cap_places = cap_lits, cap_places
        self.mobiles = {m.pid: m for m in mobiles}
        self.cles = sorted({k for m in mobiles for k in m.options}, key=lambda k: (creneaux[k].debut, k))
        self.vid = {k: i for i, k in enumerate(self.cles)}
        pids = sorted(self.mobiles)
        compat = [[self.vid[k] for k in self.mobiles[p].options] for p in pids]
        # échanges entre patients aux mêmes créneaux possibles ; la liste d'attente forme ses propres groupes
        # (sinon un échange renverrait un patient programmé en liste d'attente)
        groupes = [(frozenset(c), self.mobiles[p].place) for p, c in zip(pids, compat)]
        self._initialiser_moteur(pids, compat, groupes)
        self.indice = {p: i for i, p in enumerate(pids)}
        # ordre de passage : heure du jour actuelle (ou initiale pour la liste d'attente), puis priorité
        self.cle = {p: (m.it.debut.hour * 60 + m.it.debut.minute, -m.it.patient.priorite, p)
                    for p, m in self.mobiles.items()}
        self.cout_np = {p: self._cout_non_place(m) for p, m in self.mobiles.items()}
        # occupations figées : salle (pendant le créneau) + chirurgien du créneau (partout)
        par_salle, par_chir = defaultdict(list), defaultdict(list)
        self.charge_fixe: dict[tuple, float] = defaultdict(float)
        for it in fixes:
            par_salle[it.salle_id].append((it.debut, it.fin))
            par_chir[it.chirurgien_id].append((it.debut, it.fin))
            self.charge_fixe[(it.salle_id, it.fenetre_id)] += it.patient.duree_bloc
        self.occupe = {k: sorted([iv for iv in par_salle[k[0]] if iv[0] < creneaux[k].fin and creneaux[k].debut < iv[1]]
                                 + par_chir[creneaux[k].chirurgien_id]) for k in self.cles}
        self.jours_fixes_lits, self.jours_fixes_places = [], []
        for it in fixes:
            jours = [d for d in jours_occupation(it.patient, it.debut.date()) if d >= self.aujourdhui]
            (self.jours_fixes_places if it.patient.ambulatoire else self.jours_fixes_lits).append(jours)
        self._cache_creneau: dict = {}
        self._cache_jours: dict = {}
        # plafonds de l'agent Hébergement : occupation actuelle (programme courant) jour par jour
        self.plafond_lits, self.plafond_places = {}, {}
        etat = _EtatResiduel(self, dict(zip(self.pids, self.individu_courant())))
        self.plafond_lits, self.plafond_places = dict(etat.lits.occ), dict(etat.places.occ)

    # ------------------------------------------------------------------ construction depuis l'état du SMA
    @classmethod
    def depuis_programme(cls, maintenant: datetime, interventions: list[Intervention], garde: list[Intervention],
                    liste_attente: list[tuple[Intervention, date]], creneaux: dict[tuple[int, int], Fenetre],
                    competents: dict[int, list[int]], transferts: dict, cap_lits: int, cap_places: int,
                    parametres: ParametresSMA) -> "ProblemeResiduel":
        gel = maintenant + parametres.gel_optimisation_min * MIN
        interventions = [it.copie() for it in interventions]          # instantané : les salles évoluent ensuite
        liste_attente = [(it.copie(), j) for it, j in liste_attente]
        fixes = [it for it in interventions if it.urgence or it.debut < gel] + [it.copie() for it in garde]
        prog = {k: f for k, f in creneaux.items() if not f.urgence and f.fin > gel}

        def options(it: Intervention, actuel: Optional[tuple]) -> list[tuple]:
            p, chirs = it.patient, set(competents.get(it.pid, [it.chirurgien_initial]))
            res = [k for k, f in sorted(prog.items(), key=lambda kv: (kv[1].debut, kv[0]))
                   if f.chirurgien_id in chirs and (p.date_min is None or f.jour >= p.date_min)
                   and max(f.debut, gel) + timedelta(minutes=p.duree_bloc) <= f.fin]
            if actuel is not None and actuel not in res:
                res.insert(0, actuel)
            return res

        mobiles = []
        for it in interventions:
            if it.urgence or it.debut < gel:
                continue
            k = (it.salle_id, it.fenetre_id)
            if k not in creneaux:
                fixes.append(it)
                continue
            mobiles.append(Mobile(it, options(it, k), True, it.debut_initial.date()))
        for it, jour_ref in liste_attente:
            opts = options(it, None)
            if opts:
                mobiles.append(Mobile(it, opts, False, jour_ref))
        return cls(maintenant, gel, creneaux, fixes, mobiles, transferts, cap_lits, cap_places, parametres)

    # ------------------------------------------------------------------ interface du moteur
    def individu_courant(self):
        res = []
        for p in self.pids:
            m = self.mobiles[p]
            res.append(self.vid[(m.it.salle_id, m.it.fenetre_id)] if m.place else None)
        return res

    def etat(self, individu):
        return _EtatResiduel(self, dict(zip(self.pids, individu)))

    # ------------------------------------------------------------------ coûts élémentaires
    def _jours(self, pid: int, jour: date):
        cle = (pid, jour)
        j = self._cache_jours.get(cle)
        if j is None:
            j = self._cache_jours[cle] = tuple(d for d in jours_occupation(self.mobiles[pid].it.patient, jour)
                                               if d >= self.aujourdhui)
        return j

    def _cout_patient(self, m: Mobile, f: Fenetre, s: datetime, fin: datetime) -> float:
        it, p, P = m.it, m.it.patient, self.p
        prio = p.priorite
        jours = (s.date() - m.jour_reference).days
        if jours == 0:
            d = minutes(s - it.debut_initial)
            c = max(0.0, d) * prio * P.c_decalage_min + max(0.0, -d) * prio * P.c_avance_min
        else:
            c = P.c_deprogrammation * prio + P.c_report_jour * prio * abs(jours)
        if f.chirurgien_id != it.chirurgien_initial:
            c += P.c_changement_chirurgien
        if not p.ambulatoire:
            c += retention_sspi(fin, self.transferts.get("chambre", []), P) * P.c_retention_sspi_min
        if not m.place or (it.salle_id, it.fenetre_id) != (f.salle_id, f.id) or s != it.debut:
            c += P.c_stabilite                              # patient déplacé par rapport au programme courant
        return c

    def _cout_non_place(self, m: Mobile) -> float:
        return self.p.c_deprogrammation * m.it.patient.priorite + self.w.non_place

    def _sequencer(self, k: tuple, ordre: tuple):
        """Séquence les patients `ordre` dans le créneau k ; renvoie (coût, [(pid, début, fin)], faisable)."""
        cle = (k, ordre)
        r = self._cache_creneau.get(cle)
        if r is not None:
            return r
        f = self.creneaux[k]
        futur = f.jour > self.aujourdhui
        t = f.debut if futur else max(f.debut, self.gel)
        cout, res, faisable, charge = 0.0, [], True, self.charge_fixe.get(k, 0.0)
        for pid in ordre:
            m = self.mobiles[pid]
            duree = timedelta(minutes=m.it.patient.duree_bloc)
            mini = t
            if not futur and m.place and m.it.debut.date() == self.aujourdhui:
                mini = max(mini, m.it.debut - self.p.avance_max_min * MIN)    # convocation : au plus 1 h plus tôt
            s = premier_debut_possible(mini, duree, self.transferts.get(m.it.origine, []), self.p.transfert_min,
                                       self.occupe[k])
            fin = s + duree
            if fin > f.fin:
                faisable = False
                cout += PENALITE_HORS_HEURES + 1000 * minutes(fin - f.fin)
            cout += self._cout_patient(m, f, s, fin)
            res.append((pid, s, fin))
            charge += m.it.patient.duree_bloc
            t = fin
        if futur and charge > f.capacite_utile_min:              # marge de 10 % gardée pour les aléas futurs
            cout += (charge - f.capacite_utile_min) * self.w.depassement_vac
        r = (cout, res, faisable)
        if len(self._cache_creneau) > 200_000:
            self._cache_creneau.clear()
        self._cache_creneau[cle] = r
        return r

    def cout_actuel(self) -> float:
        """Coût du programme courant AUX HEURES ACTUELLES (sans re-séquencement) : référence du gain."""
        w = self.w
        lits, places = SuiviOccupation(self.cap_lits), SuiviOccupation(self.cap_places)
        for jours in self.jours_fixes_lits:
            lits.modifier(jours, +1)
        for jours in self.jours_fixes_places:
            places.modifier(jours, +1)
        cout, charges = 0.0, defaultdict(float)
        for m in self.mobiles.values():
            if not m.place:
                cout += self.cout_np[m.pid]
                continue
            k = (m.it.salle_id, m.it.fenetre_id)
            f = self.creneaux[k]
            cout += self._cout_patient(m, f, m.it.debut, m.it.fin)
            charges[k] += m.it.patient.duree_bloc
            (places if m.it.patient.ambulatoire else lits).modifier(self._jours(m.pid, f.jour), +1)
        for k, ch in charges.items():
            f, tot = self.creneaux[k], ch + self.charge_fixe.get(k, 0.0)
            if f.jour > self.aujourdhui and tot > f.capacite_utile_min:
                cout += (tot - f.capacite_utile_min) * w.depassement_vac
        return (cout + lits.violation * w.lit + lits.variance() * w.var_lits
                + places.violation * w.place + places.variance() * w.var_places)

    # ------------------------------------------------------------------ plan applicable
    def mouvements(self, individu) -> tuple[list[dict], bool]:
        """Patients dont le créneau ou l'heure changent ; faisable = aucun créneau hors des heures du programme
        et aucune valeur interdite."""
        etat = self.etat(individu)
        etat.score()
        faisable, res = etat.invalides == 0 and etat.lits.exces == 0 and etat.places.exces == 0, []
        for v, membres in etat.membres.items():
            if not membres:
                continue
            k = self.cles[v]
            _, placements, ok = self._sequencer(k, tuple(sorted(membres, key=self.cle.__getitem__)))
            faisable &= ok
            f = self.creneaux[k]
            for pid, s, _ in placements:
                m = self.mobiles[pid]
                actuel = (m.it.salle_id, m.it.fenetre_id) if m.place else None
                if actuel == k and s == m.it.debut:
                    continue
                nouveau = m.it.copie(patient=replace(m.it.patient, chirurgien_id=f.chirurgien_id), salle_id=k[0],
                                     fenetre_id=k[1], debut=s)
                res.append({"pid": pid, "de": actuel, "vers": k, "debut": s, "chirurgien": f.chirurgien_id,
                            "ancien": m.it, "nouveau": nouveau, "etait_place": m.place})
        return sorted(res, key=lambda x: (x["debut"], x["pid"])), faisable


# =============================================================================
# AGENT OPTIMISATION (cas A)
# =============================================================================

@dataclass
class TraceOptimisation:
    heure: datetime
    motif: str
    methode: str
    nb_mobiles: int
    cout_actuel: float
    cout_optimise: float
    evaluations: int
    temps_s: float
    applique: bool = False
    nb_mouvements: int = 0
    motif_rejet: str = ""
    courbe: list = field(default_factory=list)


class AgentOptimisation(AgentSMA):
    """Service d'optimisation globale mobilisé par la Régulation. Il ne décide rien : il propose un plan
    global ; les agents ressources le valident, la Régulation l'applique."""
    role = "optimisation"

    def __init__(self, model):
        super().__init__(model, "optimisation")
        self.historique: list[TraceOptimisation] = []
        self.problemes: list[ProblemeResiduel] = []        # capturés si parametres.capturer_problemes

    def construire(self, c: dict) -> ProblemeResiduel:
        h = self.model.instance2.hebergement
        return ProblemeResiduel.depuis_programme(c["maintenant"], c["interventions"], c["garde"], c["liste_attente"],
                                            c["creneaux"], c["competents"], c["fenetres"], h.cap_lits, h.cap_places,
                                            self.p)

    def sur_reject_proposal(self, msg: Message):
        return None

    def sur_accept_proposal(self, msg: Message):
        return None

    def sur_reoptimiser(self, msg: Message):
        c, P = msg.contenu, self.p
        pb = self.construire(c)
        if not pb.mobiles:
            return msg.reponse("INFORM", {"trace": None}, "rien à réoptimiser")
        if P.capturer_problemes:
            self.problemes.append(pb)
        actuel = pb.cout_actuel()
        res = optimiser(pb, P.optimisation_globale, temps_s=P.budget_global_s,
                        graine=self.model.random.randrange(1 << 30), rl=RL_GLOBAL, ags=AGS_GLOBAL)
        mvts, faisable = pb.mouvements(res.individu)
        trace = TraceOptimisation(self.maintenant, c.get("motif", ""), P.optimisation_globale, len(pb.mobiles), actuel,
                                  res.cout, res.evaluations, res.temps_s, nb_mouvements=len(mvts),
                                  courbe=[(pt.temps_s, pt.meilleur_score) for pt in res.suivi.historique])
        self.historique.append(trace)
        if not faisable:
            trace.motif_rejet = "plan hors des heures du programme"
        elif not mvts or res.cout > actuel - P.gain_min_global:
            trace.motif_rejet = "pas d'amélioration suffisante"
        nom = NOMS[P.optimisation_globale]
        if trace.motif_rejet:
            return msg.reponse("INFORM", {"trace": trace}, f"{nom} : score {actuel:,.0f} -> {res.cout:,.0f}, "
                                                           f"{trace.motif_rejet}")
        return msg.reponse("PROPOSE", {"trace": trace, "mouvements": mvts},
                           f"{nom} : score {actuel:,.0f} -> {res.cout:,.0f} ({len(mvts)} patient(s) déplacé(s), "
                           f"{res.evaluations} évaluations, {res.temps_s:.2f} s)")


def optimiser_localement(salle, pb: ProblemeLocalSalle):
    """Appelée par AgentSalle._ameliorer : mode et budget des agents Salle (ParametresSMA)."""
    P = salle.p
    return optimiser(pb, P.methode_locale, temps_s=P.budget_local_s,
                     graine=salle.model.random.randrange(1 << 30), rl=RL_LOCAL, ags=AGS_LOCAL)
