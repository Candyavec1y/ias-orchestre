# -*- coding: utf-8 -*-
"""Outils partagés par les pages : session, rôles, horloge, caches, mise en forme."""
from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import streamlit as st

from orchestre import programme as P
from orchestre import sma_service as S
from orchestre import stockage as DB

import structures_communes as SC

FUSEAU = ZoneInfo("Europe/Paris")
INACTIVITE_MAX = timedelta(minutes=15)          # déconnexion automatique (poste partagé au bloc)
VERROU_SIM = threading.Lock()

COULEURS = {"urgence": "#C62828", "vacation": "#1F5F8B", "libre": "#9AA5B1", "amb": "#00897B",
            "hosp": "#1F5F8B", "moi": "#E8F1F8", "alerte": "#B26A00"}

CSS = """
<style>
:root { --bleu:#1F5F8B; --bleu-clair:#E8F1F8; --ligne:#D5DDE5; --rouge:#C62828; --vert:#2E7D32; --texte:#1B2733; }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
h1, h2, h3 { color: var(--texte); letter-spacing: -0.01em; }
div[data-testid="stMetricValue"] { font-size: 1.7rem; }
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.82rem; font-weight:600;
         border:1px solid var(--ligne); background:#F5F7FA; color:#33475B; margin-right:6px; }
.badge.rouge { background:#FDECEA; color:#8E1B1B; border-color:#F5C2C0; }
.badge.vert { background:#E8F5E9; color:#1B5E20; border-color:#C8E6C9; }
.badge.bleu { background:var(--bleu-clair); color:#174A6D; border-color:#C5DCEC; }
.badge.ambre { background:#FFF4E5; color:#7A4A00; border-color:#FFD8A8; }
.grille { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 0.9rem; }
.grille th { background: var(--bleu); color:#fff; padding:8px 10px; text-align:left; font-weight:600; }
.grille th:first-child { border-top-left-radius: 8px; } .grille th:last-child { border-top-right-radius: 8px; }
.grille td { border-bottom:1px solid var(--ligne); border-right:1px solid var(--ligne); padding:6px; vertical-align:top; }
.grille td.salle { background:#F5F7FA; font-weight:600; color:var(--texte); width:90px; border-left:1px solid var(--ligne); }
.vac { border-radius:6px; padding:5px 8px; margin:3px 0; border-left:5px solid var(--bleu); background:#F7FAFC; color:var(--texte); }
.vac.moi { background:#DCEBF7; border-left-color:#0B4F80; font-weight:600; }
.vac.urgence { border-left-color: var(--rouge); background:#FDF1F0; }
.vac.libre { border-left-color:#9AA5B1; background:#F5F5F5; color:#5B6770; font-style: italic; }
.vac small { color:#5B6770; display:block; font-weight:400; }
details.vac.cliquable summary { cursor:pointer; list-style:none; }
details.vac.cliquable summary::-webkit-details-marker { display:none; }
details.vac.cliquable:hover { box-shadow:0 0 0 2px #9CC3E0; }
details.vac.cliquable[open] { background:#fff; box-shadow:0 0 0 2px var(--bleu); }
.vac .loupe { float:right; font-size:0.8rem; opacity:0.7; }
.vac table.ops { width:100%; border-collapse:collapse; margin-top:6px; font-size:0.8rem; font-weight:400; }
.vac table.ops td { border:none; border-top:1px solid var(--ligne); padding:4px 2px; vertical-align:top; }
.vac table.ops td:first-child { white-space:nowrap; color:#33475B; padding-right:6px; }
.vac .ops-vide { font-size:0.78rem; color:#5B6770; font-weight:400; margin-top:4px; }
.carte { border:1px solid var(--ligne); border-radius:10px; padding:14px 16px; background:#fff; }
.carte.ok { border-left:6px solid var(--vert); } .carte.ko { border-left:6px solid var(--rouge); }
.recit { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.82rem; white-space:pre-wrap;
         background:#F7F9FB; border:1px solid var(--ligne); border-radius:8px; padding:10px; max-height:420px; overflow:auto; color: var(--texte);}
.petit { color:#5B6770; font-size:0.85rem; }
</style>
"""


# =============================================================================
# Session et rôles
# =============================================================================

def utilisateur() -> Optional[dict]:
    return st.session_state.get("utilisateur")


def role() -> str:
    u = utilisateur()
    return u["role"] if u else ""


def est(*roles: str) -> bool:
    return role() in roles


def tracer(action: str, objet: str = "") -> None:
    u = utilisateur() or {"login": "anonyme", "role": "-"}
    DB.tracer(u["login"], u["role"], action, objet)


def verifier_inactivite() -> None:
    now = datetime.now()
    derniere = st.session_state.get("derniere_activite")
    if derniere and now - derniere > INACTIVITE_MAX and utilisateur():
        tracer("déconnexion automatique (inactivité)")
        st.session_state.clear()
        st.session_state["message_connexion"] = "Session fermée après 15 minutes d'inactivité."
        st.rerun()
    st.session_state["derniere_activite"] = now


# =============================================================================
# Horloge : temps réel ou horloge de démonstration
# =============================================================================

def horloge() -> dict:
    return DB.lire_parametre("horloge", {"mode": "reel"})


def maintenant() -> datetime:
    h = horloge()
    if h.get("mode") == "demo" and h.get("instant"):
        return datetime.fromisoformat(h["instant"])
    return datetime.now(FUSEAU).replace(tzinfo=None, second=0, microsecond=0)


def regler_horloge(instant: Optional[datetime]) -> None:
    if instant is None:
        DB.ecrire_parametre("horloge", {"mode": "reel"})
    else:
        DB.ecrire_parametre("horloge", {"mode": "demo", "instant": instant.replace(second=0, microsecond=0).isoformat()})


# =============================================================================
# Programme initial (métaheuristiques) et simulation (SMA)
# =============================================================================

def config_programme() -> Optional[dict]:
    return DB.lire_parametre("programme")


@st.cache_resource(max_entries=2, show_spinner=False)
def _programme(lundi: str, nb_semaines: int, solution_items: tuple) -> P.Programme:
    i1, i2 = P.construire_instances(date.fromisoformat(lundi), nb_semaines)
    sol = SC.SolutionPatients({int(k): v for k, v in solution_items})
    return P.Programme(date.fromisoformat(lundi), nb_semaines, "", 0, 0, i1, i2, sol)


def programme() -> Optional[P.Programme]:
    cfg = config_programme()
    if not cfg:
        return None
    prog = _programme(cfg["lundi"], cfg["nb_semaines"], tuple(sorted((int(k), v) for k, v in cfg["solution"].items())))
    prog.mode, prog.temps_s = cfg["mode"], cfg["temps_s"]
    return prog


def enregistrer_programme(prog: P.Programme, auteur: str) -> None:
    r = prog.resultat
    DB.ecrire_parametre("programme", {
        "lundi": prog.lundi.isoformat(), "nb_semaines": prog.nb_semaines, "mode": prog.mode, "temps_s": prog.temps_s,
        "graine": prog.graine, "solution": {str(k): v for k, v in prog.solution.affectations.items()},
        "score_glouton": prog.score_glouton, "score_final": r.score_final if r else prog.score_glouton,
        "score_initial": r.score_initial if r else prog.score_glouton,
        "historique": [[p.temps_s, p.meilleur_score] for p in (r.historique if r else [])],
        "calcule_le": prog.calcule_le, "auteur": auteur})


@st.cache_resource(max_entries=4, show_spinner=False)
def _simulation(cle_programme: str, empreinte: str, instant: str) -> S.Simulation:
    return S.simuler(programme(), DB.lister_evenements(), datetime.fromisoformat(instant))


def simulation() -> Optional[S.Simulation]:
    cfg = config_programme()
    if not cfg:
        return None
    cle = f"{cfg['lundi']}|{cfg['calcule_le']}"
    return _simulation(cle, DB.empreinte_evenements(), maintenant().isoformat())


def garantir_programme() -> Optional[P.Programme]:
    """Au premier lancement : calcule le programme initial de la semaine en cours (hybride mémétique)."""
    if config_programme():
        return programme()
    with st.spinner("Premier lancement : calcul du programme opératoire initial par l'hybridation "
                    "AGS + RS + Tabou (environ 10 s)…"):
        prog = P.calculer_programme(maintenant().date(), "memetique", 10.0)
        enregistrer_programme(prog, "système")
    return programme()


def synchroniser_statuts(sim: S.Simulation) -> None:
    """Met à jour le statut et la date d'intervention des fiches (sert à la purge RGPD)."""
    tous = DB.lister_evenements()
    inscrits = {e["patient_id"] for e in tous if e["patient_id"] and e["type"] == "inscription"
                and e["heure"] <= sim.maintenant}
    annules = {e["patient_id"] for e in tous if e["type"] == "annulation" and e["heure"] <= sim.maintenant}
    attente = {i.pid for i, _ in sim.en_attente()}
    for f in DB.lister_patients():
        if f["id"] not in inscrits:
            continue
        pid = S.pid_consultation(f["id"])
        it = sim.intervention(pid)
        if f["id"] in annules:
            statut, jour = "annulé", f.get("date_intervention")
        elif it is not None:
            statut = "opéré" if it.fin <= sim.maintenant else "programmé"
            jour = it.debut.date().isoformat()
        elif pid in attente:
            statut, jour = "liste d'attente", None
        else:
            statut, jour = "à programmer", None
        if statut != f["statut"] or jour != f.get("date_intervention"):
            DB.maj_patient(f["id"], statut=statut, date_intervention=jour)


# =============================================================================
# Mise en forme
# =============================================================================

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def jour_long(j: date) -> str:
    return f"{JOURS[j.weekday()]} {j.day} {MOIS[j.month - 1]}"


def libelle_semaine(t: str) -> str:
    return {"paire": "semaine paire", "impaire_1": "semaine impaire (A)", "impaire_2": "semaine impaire (B)"}.get(t, t)


def noms_patients(sim: S.Simulation) -> dict[int, str]:
    noms = {}
    for it in sim.interventions():
        noms[it.pid] = it.patient.nom or f"P{it.pid}"
    for it, _ in sim.en_attente():
        noms[it.pid] = it.patient.nom or f"P{it.pid}"
    for pid, p in sim.modele.instance2.patients.items():
        noms.setdefault(pid, p.nom or f"P{pid}")
    return noms


def lisible(texte: str, noms: dict[int, str]) -> str:
    """Remplace les identifiants internes du SMA (P123) par les pseudonymes affichés."""
    return re.sub(r"\bP(\d+)\b", lambda m: noms.get(int(m.group(1)), m.group(0)), texte)


def badge(texte: str, couleur: str = "") -> str:
    return f"<span class='badge {couleur}'>{texte}</span>"


def entete(titre: str, sous_titre: str = "") -> None:
    st.markdown(f"## {titre}")
    if sous_titre:
        st.markdown(f"<div class='petit'>{sous_titre}</div>", unsafe_allow_html=True)
