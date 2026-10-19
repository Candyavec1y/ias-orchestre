# -*- coding: utf-8 -*-
"""
Gestion dynamique par le système multi-agent (sma/sma_urgences.py).

Principe « événementiel » : la base ne stocke que le programme initial (sortie des métaheuristiques)
et la liste des événements (inscriptions issues des consultations, urgences, pannes, annulations).
L'état du bloc est obtenu en REJOUANT ces événements dans un BlocOperatoire Mesa neuf jusqu'à
l'heure courante. Avantages : état reproductible, historique complet (traçabilité), et l'effacement
d'un patient (RGPD) se fait simplement en retirant ses événements.

Les agents du dépôt ne sont pas modifiés. Deux comportements sont ajoutés côté interface, en
réutilisant les protocoles existants :
  * inscription d'un patient de consultation : appel d'offres « cfp_replacement » de l'AgentRegulation
    à toutes les AgentSalle, validation par les agents Chirurgien et Hébergement, puis le chirurgien
    choisit parmi les propositions (aide à la décision : l'humain décide) ;
  * annulation d'une intervention : la salle libère le créneau et la régulation relance la liste d'attente.
"""
from __future__ import annotations

import functools
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from . import chemins  # noqa: F401  (sys.path)

import structures_communes as SC  # noqa: E402
import planning_vacations_v28 as V28  # noqa: E402
import sma_urgences as SMA  # noqa: E402

DECALAGE_PID_CONSULTATION = 100_000
DECALAGE_PID_URGENCE = 200_000
GRAVITES = SMA.GRAVITES
LIBELLES_GRAVITE = {"vitale": "Vitale — incision < 1 h", "urgente": "Urgente — incision < 6 h",
                    "differable": "Différable — incision < 24 h"}
ASCENSEURS = {a.id: a.nom for a in SMA.Batiment().ascenseurs}
SPECIALITES = SMA.SPECIALITES_V28


def pid_consultation(patient_db_id: int) -> int:
    return DECALAGE_PID_CONSULTATION + patient_db_id


def pid_urgence(numero: int) -> int:
    return DECALAGE_PID_URGENCE + numero


def id_chirurgien(code: str) -> int:
    return V28.ID_PAR_NOM[code]


def code_chirurgien(cid: int) -> str:
    if cid == SMA.ID_CHIR_URGENCE:
        return "Chir. urgence"
    return V28.NOM_PAR_ID.get(cid, f"chir {cid}")


# =============================================================================
# Sérialisation des patients dans les événements
# =============================================================================

def patient_vers_dict(p: SC.Patient) -> dict:
    d = asdict(p)
    d["date_min"] = p.date_min.isoformat() if p.date_min else None
    return d


def patient_depuis_dict(d: dict) -> SC.Patient:
    d = dict(d)
    if d.get("date_min"):
        d["date_min"] = date.fromisoformat(d["date_min"])
    return SC.Patient(**d)


def patient_consultation(fiche: dict, valide: dict) -> SC.Patient:
    """Fiche de consultation validée par le chirurgien -> Patient des structures communes."""
    e = fiche["entrees"]
    return SC.Patient(
        id=pid_consultation(fiche["id"]), chirurgien_id=id_chirurgien(fiche["praticien"]),
        duree_bloc=int(valide["duree_bloc_min"]), ambulatoire=bool(valide["ambulatoire"]),
        nuits_pre_op=0 if valide["ambulatoire"] else int(valide["nuits_pre_op"]),
        nuits_post_op=0 if valide["ambulatoire"] else int(valide["nuits_post_op"]),
        priorite=int(valide["priorite"]), urgence=False,
        date_min=date.fromisoformat(str(valide["date_min"])), nom=fiche["pseudo"],
        age=int(e.get("age_annees", 0)), sexe={"1": "M", "2": "F"}.get(str(e.get("sexe")), "ND"),
        specialite=SPECIALITES.get(fiche["praticien"], ""), type_intervention=e.get("type_intervention", ""),
        diagnostic=e.get("cim_diag_pr", ""))


# =============================================================================
# Simulation (rejeu des événements)
# =============================================================================

@dataclass
class Simulation:
    modele: SMA.BlocOperatoire
    maintenant: datetime
    recit: list[tuple[datetime, str]] = field(default_factory=list)
    ignores: list[dict] = field(default_factory=list)        # événements hors horizon

    # ------------------------------------------------------------ consultation de l'état
    def interventions(self) -> list[SMA.Intervention]:
        return self.modele.interventions()

    def intervention(self, pid: int) -> Optional[SMA.Intervention]:
        for s in self.modele.salles.values():
            if pid in s.interventions:
                return s.interventions[pid]
        return None

    def en_attente(self) -> list[tuple[SMA.Intervention, date]]:
        return list(self.modele.regulation.liste_attente)

    def decisions(self) -> list[dict]:
        return list(self.modele.regulation.decisions)

    def alertes(self) -> list[str]:
        return list(self.modele.regulation.alertes)

    def jours(self) -> list[date]:
        return sorted(self.modele.jours_planning)

    def fenetres_du_jour(self, jour: date) -> list[SMA.Fenetre]:
        return sorted((f for s in self.modele.salles.values() for f in s.creneaux.values() if f.jour == jour),
                      key=lambda f: (f.salle_id, f.debut))

    def occupation(self, jour: date) -> dict:
        lits, places = self.modele.hebergement.occupation()
        h = self.modele.instance2.hebergement
        return {"lits": lits.get(jour, 0), "cap_lits": h.cap_lits, "reserve": h.reserve_lits,
                "places": places.get(jour, 0), "cap_places": h.cap_places}

    def pannes(self) -> dict:
        return dict(self.modele.logistique.pannes)


def construire_modele(programme) -> SMA.BlocOperatoire:
    return SMA.BlocOperatoire(programme.instance1, programme.instance2, programme.solution,
                              specialites=SMA.specialites_par_id(), chirurgien_garde=SMA.ID_CHIR_URGENCE,
                              verbeux=1)


def simuler(programme, evenements: list[dict], maintenant: datetime) -> Simulation:
    m = construire_modele(programme)
    sim = Simulation(m, maintenant)

    def annoncer(texte: str, niveau: int = 1):
        if niveau <= 1:
            for ligne in texte.strip("\n").split("\n"):
                sim.recit.append((m.maintenant, ligne))

    m.annoncer = annoncer
    _suivre_premiers_placements(m)
    fin_horizon = datetime.combine(max(m.jours_planning), time(23, 59))
    for e in evenements:
        if e["heure"] < m.t0 or e["heure"] > fin_horizon or e["heure"] > maintenant:
            sim.ignores.append(e)
            continue
        _planifier(m, e)
    if maintenant > m.t0:
        m.executer_jusqu_a(min(maintenant, fin_horizon) + timedelta(minutes=1))
    return sim


def _suivre_premiers_placements(m: SMA.BlocOperatoire) -> None:
    """Pour un patient de consultation, l'heure « initiale » (référence des décalages et du bilan) est celle
    de son PREMIER placement, et non la date au plus tôt (minuit) transmise dans l'appel d'offres."""
    places: set[int] = set()
    for salle in m.salles.values():
        origine = salle.sur_accept_proposal

        def accepter(msg, origine=origine, salle=salle):
            rep = origine(msg)
            for a in msg.contenu["plan"].ajouts:
                if DECALAGE_PID_CONSULTATION <= a.pid < DECALAGE_PID_URGENCE and a.pid not in places:
                    places.add(a.pid)
                    it = salle.interventions.get(a.pid)
                    if it is not None:
                        it.debut_initial = it.debut
            return rep

        salle.sur_accept_proposal = accepter


def _planifier(m: SMA.BlocOperatoire, e: dict) -> None:
    t, c = e["heure"], e["contenu"]
    if e["type"] == "urgence":
        m.planifier(SMA.ArriveeUrgence(t, patient_depuis_dict(c["patient"]), gravite=c["gravite"]))
    elif e["type"] == "panne":
        fin = datetime.fromisoformat(c["fin_estimee"]) if c.get("fin_estimee") else None
        m.planifier(SMA.PanneAscenseur(t, c["ascenseur"], fin))
    elif e["type"] == "prolongation":
        m.planifier(SMA.ProlongationPanne(t, c["ascenseur"], datetime.fromisoformat(c["fin_estimee"])))
    elif e["type"] == "fin_panne":
        m.planifier(SMA.FinPanne(t, c["ascenseur"]))
    elif e["type"] == "inscription":
        m.planifier_action(t, functools.partial(_inscrire, m, c))
    elif e["type"] == "annulation":
        m.planifier_action(t, functools.partial(_annuler, m, c))


# =============================================================================
# Inscription d'un patient de consultation (appel d'offres Contract Net)
# =============================================================================

def _appel_offres(m: SMA.BlocOperatoire, patient: SC.Patient, jour_min: date, chirurgiens: list[int], conv: str):
    reg = m.regulation
    apres = max(m.maintenant + m.parametres.preparation_rattrapage_min * SMA.MIN, datetime.combine(jour_min, time(0)))
    it = SMA.Intervention(patient, 0, apres, 0)
    reponses = reg.diffuser(SMA.AgentSalle, "CFP", "cfp_replacement",
                            {"intervention": it, "apres": apres, "fenetres": reg._fenetres(conv),
                             "chirurgiens": chirurgiens, "jour_reference": jour_min},
                            conv, f"placer {patient.nom} ({patient.duree_bloc} min, prio {patient.priorite})")
    props = [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]]
    valides = []
    for agent, pl in sorted(props, key=lambda x: x[1].cout):
        ok, extra, motif = reg._valider(pl, conv)
        if ok:
            valides.append((agent, pl, extra, motif))
    return it, props, valides


def chirurgiens_possibles(patient: SC.Patient, accepter_confrere: bool) -> list[int]:
    if not accepter_confrere or not patient.specialite:
        return [patient.chirurgien_id]
    ids = SMA.specialites_par_id()
    return sorted({patient.chirurgien_id} | {c for c, s in ids.items() if s == patient.specialite})


def proposer_creneaux(sim: Simulation, patient: SC.Patient, jour_min: date, accepter_confrere: bool = False,
                      nombre: int = 4) -> list[dict]:
    """Propositions SANS modifier l'état (les messages d'essai sont retirés du journal)."""
    m = sim.modele
    n0 = len(m.journal)
    ancien = m._heure_evenement
    m._heure_evenement = sim.maintenant
    try:
        _, _, valides = _appel_offres(m, patient, jour_min, chirurgiens_possibles(patient, accepter_confrere), "PROP")
        res, vus = [], set()
        for agent, pl, extra, motif in sorted(valides, key=lambda x: x[1].cout + x[2]):
            cle = (pl.salle_id, pl.fenetre_id)
            if cle in vus:
                continue
            vus.add(cle)
            res.append(_decrire_plan(sim, patient, pl, extra, motif))
            if len(res) >= nombre:
                break
        return res
    finally:
        del m.journal[n0:]
        m._heure_evenement = ancien


def _decrire_plan(sim: Simulation, patient: SC.Patient, pl, extra: float, motif: str) -> dict:
    m = sim.modele
    salle = m.salles[pl.salle_id]
    fen = salle.creneaux[pl.fenetre_id]
    debut = pl.placements[patient.id]
    nouvelle = next(a for a in pl.ajouts if a.pid == patient.id)
    deplaces = []
    for pid, s in pl.placements.items():
        if pid == patient.id:
            continue
        it = salle.interventions.get(pid)
        if it is not None and s != it.debut:
            deplaces.append({"patient": it.patient.nom or f"P{pid}", "de": it.debut, "a": s})
    evinces = [{"patient": salle.interventions[pid].patient.nom or f"P{pid}",
                "priorite": salle.interventions[pid].patient.priorite} for pid in pl.retraits]
    occ = sim.occupation(debut.date())
    return {
        "salle_id": pl.salle_id, "salle": salle.nom_affiche, "fenetre_id": pl.fenetre_id,
        "jour": debut.date(), "debut": debut, "fin": debut + timedelta(minutes=patient.duree_bloc),
        "vacation": f"{fen.debut:%H:%M}–{fen.fin:%H:%M}", "chirurgien": code_chirurgien(nouvelle.chirurgien_id),
        "changement_chirurgien": nouvelle.chirurgien_id != patient.chirurgien_id,
        "cout": pl.cout + extra, "detail": dict(pl.detail), "deplaces": deplaces, "evinces": evinces,
        "hebergement": motif or "capacité OK", "lits_jour": f"{occ['lits']}/{occ['cap_lits']}",
        "places_jour": f"{occ['places']}/{occ['cap_places']}",
    }


def _inscrire(m: SMA.BlocOperatoire, c: dict) -> None:
    """Rejeu d'une inscription : applique la proposition choisie par le chirurgien (même salle et même
    créneau) si elle est toujours valide, sinon la meilleure proposition, sinon la liste d'attente."""
    reg = m.regulation
    p = patient_depuis_dict(c["patient"])
    jour_min = date.fromisoformat(c["jour_min"])
    conv = m.nouvelle_conversation("CONS")
    reg.chirurgiens_autorises[p.id] = sorted(c.get("chirurgiens") or [p.chirurgien_id])   # relances / replacements
    m.annoncer(f"\n[{SMA.jour_txt(m.maintenant.date())} {SMA.hm(m.maintenant)}] {conv} — CONSULTATION : {p.nom} "
               f"(Dr {code_chirurgien(p.chirurgien_id)}, {p.duree_bloc} min, priorité {p.priorite}, "
               f"{'ambulatoire' if p.ambulatoire else 'hospitalisé'}, au plus tôt le {jour_min:%d/%m})")
    if c.get("attente"):
        apres = max(m.maintenant, datetime.combine(jour_min, time(0)))
        reg.liste_attente.append((SMA.Intervention(p, 0, apres, 0), jour_min))
        m.annoncer(f"  {p.nom} inscrit(e) en liste d'attente (relance chaque matin et à chaque créneau libéré)")
        reg.decisions.append({"type": "consultation_attente", "heure": m.maintenant, "patient": p.id})
        return
    it, props, valides = _appel_offres(m, p, jour_min, reg.chirurgiens_autorises[p.id], conv)
    choix = None
    voulu = (c.get("salle_id"), c.get("fenetre_id"))
    meme = [v for v in valides if (v[1].salle_id, v[1].fenetre_id) == voulu]
    if meme:
        choix = min(meme, key=lambda v: v[1].cout + v[2])
    elif valides:
        choix = min(valides, key=lambda v: v[1].cout + v[2])
        if voulu[0] is not None:
            m.annoncer("  Le créneau choisi n'est plus disponible : meilleure alternative retenue")
    if choix is None:
        reg.liste_attente.append((it, jour_min))
        m.annoncer(f"  {p.nom} : aucune place sur les heures du planning -> liste d'attente")
        reg.decisions.append({"type": "consultation_attente", "heure": m.maintenant, "patient": p.id})
        return
    agent, plan, extra, note = choix
    retirees = reg._appliquer(agent, plan, props, conv)
    debut = plan.placements[p.id]
    m.annoncer(f"  {p.nom} programmé(e) le {SMA.jour_txt(debut.date())} à {SMA.hm(debut)} en "
               f"{m.annuaire[agent].nom_affiche} ({len(props)} propositions reçues, coût {plan.cout + extra:,.0f})")
    m.annoncer(f"    {plan.resume}")
    if note:
        m.annoncer(f"    Contraintes signalées : {note}")
    reg.decisions.append({"type": "consultation", "heure": m.maintenant, "patient": p.id, "debut": debut,
                          "salle": plan.salle_id, "chirurgien": plan.ajouts[0].chirurgien_id,
                          "cout": plan.cout + extra, "plan": plan.resume, "nb_propositions": len(props)})
    reg._replacer(retirees, conv)


def _annuler(m: SMA.BlocOperatoire, c: dict) -> None:
    reg = m.regulation
    pid = int(c["pid"])
    conv = m.nouvelle_conversation("ANN")
    m.annoncer(f"\n[{SMA.jour_txt(m.maintenant.date())} {SMA.hm(m.maintenant)}] {conv} — ANNULATION : "
               f"{c.get('nom', f'P{pid}')} ({c.get('motif', 'motif non précisé')})")
    avant = len(reg.liste_attente)
    reg.liste_attente = [(i, j) for i, j in reg.liste_attente if i.pid != pid]
    if len(reg.liste_attente) < avant:
        m.annoncer("  retiré(e) de la liste d'attente")
        return
    for s in m.salles.values():
        it = s.interventions.get(pid)
        if it is None:
            continue
        if it.debut <= m.maintenant:
            m.annoncer("  intervention déjà commencée : annulation impossible")
            return
        plan = SMA.Plan(s.salle_id, it.fenetre_id, it.debut.date(), {}, retraits=[pid])
        reg.envoyer(f"salle_{s.salle_id}", "ACCEPT_PROPOSAL", "accept_proposal", {"plan": plan}, conv,
                    f"libérer {it.patient.nom or pid}")
        m.annoncer(f"  créneau libéré : {s.nom_affiche} {SMA.jour_txt(it.debut.date())} {SMA.hm(it.debut)}")
        reg.decisions.append({"type": "annulation", "heure": m.maintenant, "patient": pid, "salle": s.salle_id})
        reg._relancer_attente(conv, m.maintenant + m.parametres.preparation_rattrapage_min * SMA.MIN)
        return
    m.annoncer("  intervention introuvable")


# =============================================================================
# Urgences
# =============================================================================

def patient_urgent(numero: int, code_praticien: str, duree: int, *, ambulatoire: bool, nuits_post_op: int,
                   diagnostic: str = "", type_intervention: str = "", age: int = 40) -> SC.Patient:
    return SMA.patient_urgent(pid_urgence(numero), id_chirurgien(code_praticien), duree,
                              specialite=SPECIALITES.get(code_praticien, ""), ambulatoire=ambulatoire,
                              nuits_post_op=nuits_post_op, nom=f"URG-{numero:03d}", diagnostic=diagnostic,
                              age=age, type_intervention=type_intervention)
