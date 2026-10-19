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
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Optional

from . import chemins  # noqa: F401  (sys.path)
from . import programme as P

import structures_communes as SC  # noqa: E402
import planning_vacations_v28 as V28  # noqa: E402
import sma_urgences as SMA  # noqa: E402

DECALAGE_PID_CONSULTATION = 100_000
DECALAGE_PID_URGENCE = 200_000
GRAVITES = SMA.GRAVITES
LIBELLES_GRAVITE = {"vitale": "Vitale — incision < 1 h", "urgente": "Urgente — incision < 6 h",
                    "differable": "Différable — incision < 24 h"}
ASCENSEURS = {a.id: a.nom for a in SMA.Batiment().ascenseurs}
SPECIALITES = SMA.SPECIALITES_V28          # (compatibilité) ; utiliser SMA.specialite_de(code)


def pid_consultation(patient_db_id: int) -> int:
    return DECALAGE_PID_CONSULTATION + patient_db_id


def pid_urgence(numero: int) -> int:
    return DECALAGE_PID_URGENCE + numero


def id_chirurgien(code: str) -> int:
    return V28.ID_PAR_NOM[code]


def code_chirurgien(cid: int) -> str:
    if cid == SMA.ID_CHIR_URGENCE:
        return "Chir. urgence"
    if cid == SMA.ID_EQUIPE_GARDE:
        return "Équipe de garde"
    return V28.NOM_PAR_ID.get(cid, f"chir {cid}")


def nom_chirurgien(cid: int) -> str:
    """« Dr CT », ou « Chir. urgence » / « Équipe de garde » (pas de « Dr » devant)."""
    return code_chirurgien(cid) if cid in (SMA.ID_CHIR_URGENCE, SMA.ID_EQUIPE_GARDE) else f"Dr {code_chirurgien(cid)}"


# =============================================================================
# Sérialisation des patients dans les événements
# =============================================================================

def patient_vers_dict(p: SC.Patient) -> dict:
    d = asdict(p)
    d["date_min"] = p.date_min.isoformat() if p.date_min else None
    return d


def patient_depuis_dict(d: dict) -> SC.Patient:
    d = dict(d)
    # la spécialité vient TOUJOURS du chirurgien (les événements anciens portent d'anciennes valeurs : « Orthopédie »,
    # « Main »...) : tous les praticiens du planning sont du même service
    d["specialite"] = SMA.specialite_de(V28.NOM_PAR_ID.get(d.get("chirurgien_id"), ""))
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
        specialite=SMA.specialite_de(fiche["praticien"]), type_intervention=e.get("type_intervention", ""),
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
        """Interventions des salles du programme ET du planning de garde."""
        return sorted(self.modele.interventions() + list(self.modele.garde.interventions.values()),
                      key=lambda i: (i.debut, i.salle_id))

    def intervention(self, pid: int) -> Optional[SMA.Intervention]:
        for s in self.salles():
            if pid in s.interventions:
                return s.interventions[pid]
        return None

    def salles(self, jour: Optional[date] = None) -> list:
        """Salles du programme, plus la salle de garde si elle a des interventions (ce jour-là si `jour`)."""
        g = self.modele.garde
        avec_garde = g.du_jour(jour) if jour is not None else g.interventions
        return list(self.modele.salles.values()) + ([g] if avec_garde else [])

    def en_attente(self) -> list[tuple[SMA.Intervention, date]]:
        return list(self.modele.regulation.liste_attente)

    def decisions(self) -> list[dict]:
        return list(self.modele.regulation.decisions)

    def alertes(self) -> list[str]:
        return list(self.modele.regulation.alertes)

    def alertes_horodatees(self) -> list[tuple[datetime, str]]:
        a = self.modele.regulation.alertes
        return list(zip(getattr(a, "heures", [self.maintenant] * len(a)), a))

    def jours(self) -> list[date]:
        return sorted(self.modele.jours_planning)

    def jours_tendances(self, semaines: int = 4) -> list[date]:
        """Jours des graphiques de tendance : les semaines du programme optimisé, prolongées jusqu'à `semaines`
        semaines après aujourd'hui (le SMA, lui, connaît toute l'année)."""
        jours = self.jours()
        if not jours:
            return []
        fin = max(jours[0] + timedelta(weeks=P.NB_SEMAINES_HORIZON) - timedelta(days=1),
                  self.maintenant.date() + timedelta(weeks=semaines))
        return [j for j in jours if j <= fin]

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


class AlertesHorodatees(list):
    """Liste d'alertes du SMA (chaînes, comme avant) qui retient aussi l'heure du modèle à laquelle chacune est levée."""

    def __init__(self, modele: SMA.BlocOperatoire):
        super().__init__()
        self.modele, self.heures = modele, []

    def append(self, alerte: str) -> None:
        super().append(alerte)
        self.heures.append(self.modele.maintenant)


def construire_modele(programme) -> SMA.BlocOperatoire:
    # Site : optimisations locale ET globale désactivées. Le site rejoue tous les événements à chaque affichage ; depuis
    # que tous les praticiens sont du même service, l'optimisation locale coûtait ~17 s par rejeu sans gain de score
    # mesuré (19,5 s -> 2,6 s, score identique). L'optimisation globale reste disponible à la demande (Administration).
    i1, i2 = P.instances_sma(programme)          # planning des vacations fixe sur toutes les semaines à venir
    m = SMA.BlocOperatoire(i1, i2, programme.solution,
                              specialites=SMA.specialites_par_id(), chirurgien_garde=SMA.ID_CHIR_URGENCE,
                              parametres=SMA.ParametresSMA(optimisation_globale=None, methode_locale=None), verbeux=1)
    m.regulation.alertes = AlertesHorodatees(m)
    return m


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
        evt = SMA.ArriveeUrgence(t, patient_depuis_dict(c["patient"]), gravite=c["gravite"])
        m.evenements.append(evt)
        m.planifier_action(t, functools.partial(_urgence_tracee, m, evt))
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
    elif e["type"] == "reoptimisation":
        m.planifier_action(t, functools.partial(_reoptimisation_rejouee, m, c))
    elif e["type"] == "absence":
        m.planifier_action(t, functools.partial(_absence, m, c))


def etat_programme(m: SMA.BlocOperatoire) -> dict[int, tuple]:
    """pid -> ("programmé", salle, début, chirurgien) ou ("attente", None, None, chirurgien)."""
    its = m.interventions() + list(m.garde.interventions.values())
    etat = {it.pid: ("programmé", it.salle_id, it.debut, it.chirurgien_id) for it in its}
    for it, _ in m.regulation.liste_attente:
        etat[it.pid] = ("attente", None, None, it.chirurgien_initial)
    return etat


# =============================================================================
# Optimisation globale demandée par l'administrateur
# =============================================================================
# La métaheuristique tourne UNE fois (calculer_reoptimisation) ; l'événement enregistre son RÉSULTAT (les
# déplacements), que chaque rejeu réapplique tel quel : rejeu rapide et toujours identique.

def calculer_reoptimisation(programme, evenements: list[dict], maintenant: datetime, methode: str,
                            budget_s: float) -> tuple[Optional[dict], str, dict]:
    """Rejoue l'état courant, lance l'optimisation globale du SMA (agent Optimisation, contrôle groupé des agents
    Chirurgien et Hébergement) et renvoie (contenu de l'événement ou None, message, scores)."""
    sim = simuler(programme, evenements, maintenant)
    m = sim.modele
    avant_score = m.score_programme()["total"]
    avant = etat_programme(m)
    m.parametres = replace(m.parametres, optimisation_globale=methode, budget_global_s=budget_s)
    n0 = len(m.optimisation.historique)
    m._heure_evenement = maintenant
    try:
        m.regulation.reoptimiser(m.nouvelle_conversation("OPT"), "demande de l'administrateur")
    finally:
        m._heure_evenement = None
    trace = m.optimisation.historique[-1] if len(m.optimisation.historique) > n0 else None
    scores = {"avant": avant_score, "apres": m.score_programme()["total"],
              "estime_avant": trace.cout_actuel if trace else None, "estime_apres": trace.cout_optimise if trace else None,
              "temps_s": trace.temps_s if trace else 0.0, "evaluations": trace.evaluations if trace else 0}
    if trace is None:
        return None, "Rien à réoptimiser (aucun patient déplaçable).", scores
    if not trace.applique:
        return None, f"Aucun plan appliqué : {trace.motif_rejet or 'pas d’amélioration'}.", scores
    apres = etat_programme(m)
    par_pid = {it.pid: it for it in m.interventions()}
    mouvements = []
    for pid, b in apres.items():
        if b[0] != "programmé" or avant.get(pid) == b or pid not in par_pid:
            continue
        it = par_pid[pid]
        mouvements.append({"pid": pid, "salle_id": it.salle_id, "fenetre_id": it.fenetre_id,
                           "debut": it.debut.isoformat(), "chirurgien_id": it.chirurgien_id})
    contenu = {"methode": methode, "budget_s": budget_s, "mouvements": mouvements,
               "score_avant": scores["avant"], "score_apres": scores["apres"]}
    return contenu, f"{len(mouvements)} patient(s) déplacé(s).", scores


def _reoptimisation_rejouee(m: SMA.BlocOperatoire, c: dict) -> None:
    """Réapplique les déplacements enregistrés, après les mêmes contrôles que le SMA (agendas, lits, salles)."""
    reg = m.regulation
    conv = m.nouvelle_conversation("OPT")
    m.annoncer(f"\n[{SMA.jour_txt(m.maintenant.date())} {SMA.hm(m.maintenant)}] {conv} — OPTIMISATION GLOBALE "
               f"demandée par l'administrateur ({c.get('methode')}, {c.get('budget_s')} s) : "
               f"{len(c['mouvements'])} déplacement(s) à appliquer")
    places = {pid: it for s in m.salles.values() for pid, it in s.interventions.items()}
    attente = {it.pid: it for it, _ in reg.liste_attente}
    mvts, motif = [], ""
    for mv in c["mouvements"]:
        pid, debut = mv["pid"], datetime.fromisoformat(mv["debut"])
        ancien = places.get(pid) or attente.get(pid)
        salle = m.salles.get(mv["salle_id"]) if mv["salle_id"] in m.salles else None
        fen = salle.creneaux.get(mv["fenetre_id"]) if salle else None
        if ancien is None or fen is None:
            motif = f"P{pid} ou son créneau n'existe plus"
            break
        if debut <= m.maintenant or (pid in places and ancien.debut <= m.maintenant):
            motif = f"P{pid} : intervention déjà commencée"
            break
        nouveau = ancien.copie(patient=replace(ancien.patient, chirurgien_id=fen.chirurgien_id),
                               salle_id=fen.salle_id, fenetre_id=fen.id, debut=debut)
        mvts.append({"pid": pid, "de": (ancien.salle_id, ancien.fenetre_id) if pid in places else None,
                     "vers": (fen.salle_id, fen.id), "debut": debut, "chirurgien": fen.chirurgien_id,
                     "ancien": ancien, "nouveau": nouveau, "etait_place": pid in places})
    if not motif:
        # salles : pas de chevauchement dans chaque créneau d'arrivée, et rien hors des heures du planning
        bouges = {mv["pid"] for mv in mvts}
        for (sid, fid) in {mv["vers"] for mv in mvts}:
            fen = m.salles[sid].creneaux[fid]
            its = sorted([(i.debut, i.fin) for i in m.salles[sid].du_creneau(fid) if i.pid not in bouges]
                         + [(mv["nouveau"].debut, mv["nouveau"].fin) for mv in mvts if mv["vers"] == (sid, fid)])
            if its and (its[0][0] < fen.debut or its[-1][1] > fen.fin) or any(b[0] < a[1] for a, b in zip(its, its[1:])):
                motif = f"{m.salles[sid].nom_affiche} : le plan ne tient plus dans le créneau"
                break
    if not motif:
        ok, rejet = reg._valider_global(mvts, conv)
        motif = "" if ok else rejet
    if motif:
        alerte = f"Optimisation globale de l'administrateur non appliquée : {motif} (programme modifié depuis)"
        reg.alertes.append(alerte)
        m.annoncer(f"  ⚠ {alerte}")
        return
    jour = m.maintenant.date()
    departs: dict[int, list[int]] = {}
    for mv in mvts:
        if mv["etait_place"]:
            departs.setdefault(mv["de"][0], []).append(mv["pid"])
    for sid, pids in sorted(departs.items()):
        reg.envoyer(f"salle_{sid}", "ACCEPT_PROPOSAL", "accept_proposal",
                    {"plan": SMA.Plan(sid, SMA.ID_FENETRE_GARDE, jour, {}, retraits=pids)}, conv,
                    f"optimisation : libérer {', '.join(f'P{p}' for p in pids)}")
    arrivees: dict[int, list] = {}
    for mv in mvts:
        arrivees.setdefault(mv["vers"][0], []).append(mv["nouveau"])
    for sid, its in sorted(arrivees.items()):
        reg.envoyer(f"salle_{sid}", "ACCEPT_PROPOSAL", "accept_proposal",
                    {"plan": SMA.Plan(sid, SMA.ID_FENETRE_GARDE, jour, {it.pid: it.debut for it in its}, ajouts=its)},
                    conv, f"optimisation : placer {', '.join(f'P{it.pid}' for it in its)}")
    sortis = {mv["pid"] for mv in mvts if not mv["etait_place"]}
    reg.liste_attente = [(it, j) for it, j in reg.liste_attente if it.pid not in sortis]
    m.annoncer(f"  ✦ {len(mvts)} patient(s) déplacé(s), score {c.get('score_avant', 0):,.0f} → {c.get('score_apres', 0):,.0f}")
    reg.decisions.append({"type": "reoptimisation", "heure": m.maintenant, "motif": "demande de l'administrateur",
                          "methode": c.get("methode"), "patients_deplaces": len(mvts),
                          "patients_sortis_attente": len(sortis),
                          "gain": c.get("score_avant", 0) - c.get("score_apres", 0)})


# =============================================================================
# Absence d'un chirurgien (vacances, congrès, maladie...)
# =============================================================================
# Les vacations du chirurgien sont fermées sur la période (les salles ne les proposent plus, son agent refuse tout
# créneau) ; ses patients non commencés sont replacés aussitôt : chez un confrère SEULEMENT s'il l'a accepté à la
# consultation, sinon dans les vacations de son chirurgien après son retour (priorité puis ordre de passage).

SEUIL_ALERTE_REPORT_JOURS = 3          # patient prioritaire (3-4) repoussé de plus de 3 jours : alerte au cadre
PREVENANCE_JOURS = 2                   # un patient replacé l'est au plus tôt 2 jours après la déclaration (le prévenir)


def periode_absence(c: dict) -> tuple[datetime, datetime]:
    """[premier jour 0 h, lendemain du dernier jour 0 h[."""
    return (datetime.combine(date.fromisoformat(c["du"]), time(0)),
            datetime.combine(date.fromisoformat(c["au"]) + timedelta(days=1), time(0)))


def _absence(m: SMA.BlocOperatoire, c: dict) -> None:
    reg = m.regulation
    cid = id_chirurgien(c["praticien"])
    debut, fin = periode_absence(c)
    conv = m.nouvelle_conversation("ABS")
    m.absences.setdefault(cid, []).append((debut, fin))
    m.annoncer(f"\n[{SMA.jour_txt(m.maintenant.date())} {SMA.hm(m.maintenant)}] {conv} — ABSENCE : Dr {c['praticien']} "
               f"du {debut:%d/%m} au {fin - timedelta(days=1):%d/%m} ({c.get('motif', 'motif non précisé')}) : "
               f"ses vacations sur la période sont fermées")
    apres = m.maintenant + m.parametres.preparation_rattrapage_min * SMA.MIN
    au_plus_tot = datetime.combine(m.maintenant.date() + timedelta(days=PREVENANCE_JOURS), time(0))
    touches = sorted((it for s in m.salles.values() for it in s.interventions.values()
                      if it.chirurgien_id == cid and debut <= it.debut < fin and it.debut > m.maintenant),
                     key=lambda i: (-i.patient.priorite, i.debut))
    for it in touches:
        if it.debut < apres:
            alerte = (f"Absence du Dr {c['praticien']} : P{it.pid} prévu à {SMA.hm(it.debut)} ne peut plus être "
                      f"opéré par lui et est peut-être déjà convoqué -> prévenir le patient")
            reg.alertes.append(alerte)
            m.annoncer(f"  ⚠ {alerte}")
    for it in touches:                        # libérer les créneaux (agendas et séjours mis à jour par la salle)
        reg.envoyer(f"salle_{it.salle_id}", "ACCEPT_PROPOSAL", "accept_proposal",
                    {"plan": SMA.Plan(it.salle_id, it.fenetre_id, it.debut.date(), {}, retraits=[it.pid])}, conv,
                    f"absence : libérer P{it.pid}")
    reg.decisions.append({"type": "absence", "heure": m.maintenant, "chirurgien": cid, "du": debut, "au": fin,
                          "patients_touches": len(touches)})
    if not touches:
        m.annoncer("  ✔ Aucun patient programmé sur la période")
        return
    m.annoncer(f"  {len(touches)} patient(s) à replacer")
    urgences = [it for it in touches if it.urgence and it.pid in reg.urgences_info]
    if urgences:
        reg._replacer(urgences, conv)           # une urgence garde son délai : nouvel appel d'offres urgence
    for it in [i for i in touches if i not in urgences]:
        autorises = reg.chirurgiens_autorises.get(it.pid, [it.chirurgien_initial])
        reponses = reg.diffuser(SMA.AgentSalle, "CFP", "cfp_replacement",
                                {"intervention": it, "apres": au_plus_tot, "fenetres": reg._fenetres(conv),
                                 "agendas": reg._agendas(conv), "chirurgiens": autorises,
                                 "jour_reference": it.debut.date()},
                                conv, f"replacer P{it.pid} (absence du Dr {c['praticien']})")
        props = [(r.emetteur, pl) for r in reponses if r.performatif == "PROPOSE" for pl in r.contenu["plans"]]
        choix = reg._choisir(props, conv, lambda pl: (False, pl.cout))
        if choix is None:
            reg.liste_attente.append((it, it.debut.date()))
            m.annoncer(f"    ↳ P{it.pid} : aucune vacation compatible -> liste d'attente")
            reg.decisions.append({"type": "attente", "heure": m.maintenant, "patient": it.pid})
            continue
        agent, plan, extra, _ = choix
        evinces = reg._appliquer(agent, plan, props, conv)
        nouvelle = plan.ajouts[0]
        m.annoncer(f"    ↳ {plan.resume}")
        reg.decisions.append({"type": "replacement", "heure": m.maintenant, "patient": it.pid, "debut": nouvelle.debut,
                              "salle": plan.salle_id, "chirurgien": nouvelle.chirurgien_id,
                              "changement_chirurgien": nouvelle.chirurgien_id != nouvelle.chirurgien_initial,
                              "cout": plan.cout + extra, "motif": "absence"})
        report = (nouvelle.debut.date() - it.debut.date()).days
        if it.patient.priorite >= 3 and report > SEUIL_ALERTE_REPORT_JOURS:
            alerte = (f"Absence du Dr {c['praticien']} : P{it.pid} (priorité {it.patient.priorite}) repoussé de "
                      f"{report} jours, au {SMA.jour_txt(nouvelle.debut.date())} -> à valider par le cadre de bloc")
            reg.alertes.append(alerte)
            m.annoncer(f"  ⚠ {alerte}")
        if evinces:
            reg._replacer(evinces, conv)


def _urgence_tracee(m: SMA.BlocOperatoire, evt) -> None:
    """Traite l'urgence et garde l'état du programme juste avant / juste après (patients qu'elle a déplacés),
    sans rejouer la simulation une seconde fois."""
    avant = etat_programme(m)
    m._declencher(evt)
    if not hasattr(m, "traces_urgences"):
        m.traces_urgences = {}
    m.traces_urgences[evt.patient.id] = (avant, etat_programme(m))


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
               f"({nom_chirurgien(p.chirurgien_id)}, {p.duree_bloc} min, priorité {p.priorite}, "
               f"{'ambulatoire' if p.ambulatoire else 'hospitalisé'}, au plus tôt le {jour_min:%d/%m})")
    # Planning des vacations fixe sur toutes les semaines à venir : le patient est toujours placé tout de suite (une
    # ancienne inscription « en liste d'attente », c["attente"], est traitée comme les autres). La liste d'attente ne
    # reste qu'un filet de sécurité, si aucune vacation compatible n'existe.
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
                              specialite=SMA.specialite_de(code_praticien), ambulatoire=ambulatoire,
                              nuits_post_op=nuits_post_op, nom=f"URG-{numero:03d}", diagnostic=diagnostic,
                              age=age, type_intervention=type_intervention)
