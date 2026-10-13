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

COULEURS = {"urgence": "#C62828", "vacation": "#2626F5", "libre": "#9AA5B1", "amb": "#3CCB94",
            "hosp": "#2626F5", "moi": "#E6EAFF", "alerte": "#B26A00"}

# Charte des présentations : bleu électrique, bleu pervenche, vert menthe ; titres larges en capitales.
POLICE_TITRES = "'PP Neue Machina', 'Archivo', sans-serif"

LOGO = """<svg class="logo-ias" viewBox="0 0 40 40" aria-hidden="true">
<path d="M17 17 L17 2.25 A18 18 0 0 0 2.25 17 Z" fill="#5B7BF9"/>
<path d="M23 17 L37.75 17 A18 18 0 0 0 23 2.25 Z" fill="#2626F5"/>
<path d="M17 23 L2.25 23 A18 18 0 0 0 17 37.75 Z" fill="#62E8B4"/>
<path d="M23 23 L23 37.75 A18 18 0 0 0 37.75 23 Z" fill="#5B7BF9"/></svg>"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=Raleway:ital,wght@0,400..800;1,400..800&family=Quicksand:wght@400..700&display=swap');
:root { --electrique:#2626F5; --pervenche:#5B7BF9; --menthe:#62E8B4; --menthe-fonce:#1E9E6E; --menthe-clair:#E4F8F0;
        --bleu:#2626F5; --bleu-clair:#E6EAFF; --ligne:#D5DCFA; --rouge:#C62828; --vert:#1E9E6E; --texte:#17175E;
        --discret:#4A5591; --titres:""" + POLICE_TITRES + """; }
.stApp { background: linear-gradient(120deg, #FFFFFF 0%, #F4FCF9 45%, #D6F7EA 100%) fixed; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { font-family: var(--titres) !important; font-stretch: 118%; font-weight: 800;
        text-transform: uppercase; letter-spacing: 0.01em; color: var(--electrique); }
.stApp h5, .stApp h6 { color: var(--electrique); }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 { color:#fff; }

/* indicateurs : cartes blanches à ombre décalée, comme les blocs des présentations */
div[data-testid="stMetric"] { background:#fff; border:1px solid var(--ligne); border-radius:8px; padding:12px 14px;
        box-shadow: 6px 6px 0 rgba(91,123,249,0.22); }
div[data-testid="stMetricValue"] { font-size: 1.7rem; font-family: var(--titres); font-stretch: 112%; font-weight: 800; color: var(--electrique); }

/* boutons */
button[data-testid^="stBaseButton-primary"] { background: var(--electrique); border-color: var(--electrique);
        text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; box-shadow: 4px 4px 0 rgba(98,232,180,0.55); }
button[data-testid^="stBaseButton-primary"]:hover { background: var(--pervenche); border-color: var(--pervenche); }
button[data-testid^="stBaseButton-secondary"] { font-weight: 600; }

/* onglets */
div[data-baseweb="tab-highlight"] { background: var(--electrique); height: 3px; }

/* barre latérale bleu électrique */
section[data-testid="stSidebar"] .petit { color: rgba(255,255,255,0.78); }
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(98,232,180,0.28); }
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]:hover { background: rgba(255,255,255,0.14); }
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] { color: var(--menthe); letter-spacing: 0.08em; text-transform: uppercase; }
section[data-testid="stSidebar"] button[data-testid^="stBaseButton-secondary"] { background: transparent; color:#fff; border-color: rgba(255,255,255,0.6); }
section[data-testid="stSidebar"] button[data-testid^="stBaseButton-secondary"]:hover { background:#fff; color: var(--electrique); border-color:#fff; }

/* marque */
.logo-ias { width: 34px; height: 34px; flex: none; }
.marque { display:flex; align-items:center; gap:10px; margin-bottom: 4px; }
.marque .nom { font-family: var(--titres); font-stretch: 118%; font-weight: 800; font-size: 1.35rem; line-height: 1; color: var(--electrique); }
.marque .sous { font-family: 'Quicksand', sans-serif; font-size: 0.62rem; letter-spacing: 0.22em; text-transform: uppercase; color: var(--pervenche); margin-top: 3px; }
section[data-testid="stSidebar"] .marque .nom { color:#fff; }
section[data-testid="stSidebar"] .marque .sous { color: var(--menthe); }
section[data-testid="stSidebar"] .logo-ias path[fill="#2626F5"] { fill:#fff; }
.hero { margin: 8vh 0 26px; }
.hero .titre { font-family: var(--titres); font-stretch: 125%; font-weight: 900; font-size: clamp(2rem, 4.2vw, 3.6rem);
        line-height: 1; white-space: nowrap; color: var(--electrique); letter-spacing: 0.01em; margin-top: 34px; }
.hero .accroche { font-family: 'Quicksand', sans-serif; font-size: clamp(0.85rem, 1.6vw, 1.25rem); letter-spacing: 0.24em;
        text-transform: uppercase; color: var(--pervenche); margin: 6px 0 18px; }
.arc-deco { position: fixed; right: -34vw; top: 50%; transform: translateY(-50%); width: 72vw; height: 72vw; max-height: 140vh;
        border-radius: 50%; background: linear-gradient(150deg, #2626F5 0%, #5B7BF9 60%, #8FD9F0 100%);
        box-shadow: 0 0 0 10px #5B7BF9, 0 0 0 34px #2626F5, 0 0 0 52px #62E8B4; z-index: 0; pointer-events: none; }
@media (max-width: 900px) { .arc-deco { display: none; } }

/* éléments métier */
.badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.82rem; font-weight:600;
         border:1px solid var(--ligne); background:#F4F6FF; color:#2A2F7A; margin-right:6px; }
.badge.rouge { background:#FDECEA; color:#8E1B1B; border-color:#F5C2C0; }
.badge.vert { background:var(--menthe-clair); color:#0F6B48; border-color:#A8EBD0; }
.badge.bleu { background:var(--bleu-clair); color:#1C1CB8; border-color:#C2CCFC; }
.badge.ambre { background:#FFF4E5; color:#7A4A00; border-color:#FFD8A8; }
.grille { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 0.9rem; background:#fff; }
.grille th { background: var(--electrique); color:#fff; padding:8px 10px; text-align:left; font-weight:700;
             text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.78rem; }
.grille th:first-child { border-top-left-radius: 8px; } .grille th:last-child { border-top-right-radius: 8px; }
.grille td { border-bottom:1px solid var(--ligne); border-right:1px solid var(--ligne); padding:6px; vertical-align:top; }
.grille td.salle { background:var(--menthe-clair); font-weight:700; color:var(--texte); width:90px; border-left:1px solid var(--ligne); }
.vac { border-radius:6px; padding:5px 8px; margin:3px 0; border-left:5px solid var(--pervenche); background:#F5F7FF; color:var(--texte); }
.vac.moi { background:#E1E6FF; border-left-color:var(--electrique); font-weight:600; }
.vac.urgence { border-left-color: var(--rouge); background:#FDF1F0; }
.vac.libre { border-left-color:#9AA5B1; background:#F5F5F5; color:#5B6770; font-style: italic; }
.vac small { color:var(--discret); display:block; font-weight:400; }
details.vac.cliquable summary { cursor:pointer; list-style:none; }
details.vac.cliquable summary::-webkit-details-marker { display:none; }
details.vac.cliquable:hover { box-shadow:0 0 0 2px #AEBDFC; }
details.vac.cliquable[open] { background:#fff; box-shadow:0 0 0 2px var(--electrique); }
.vac .loupe { float:right; font-size:0.8rem; opacity:0.7; }
.vac table.ops { width:100%; border-collapse:collapse; margin-top:6px; font-size:0.8rem; font-weight:400; }
.vac table.ops td { border:none; border-top:1px solid var(--ligne); padding:4px 2px; vertical-align:top; }
.vac table.ops td:first-child { white-space:nowrap; color:#2A2F7A; padding-right:6px; }
.vac .ops-vide { font-size:0.78rem; color:var(--discret); font-weight:400; margin-top:4px; }
.carte { border:1px solid var(--ligne); border-radius:10px; padding:14px 16px; background:#fff; box-shadow: 6px 6px 0 rgba(91,123,249,0.18); }
.carte.ok { border-left:6px solid var(--menthe-fonce); } .carte.ko { border-left:6px solid var(--rouge); }
.recit { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.82rem; white-space:pre-wrap;
         background:#F7F9FF; border:1px solid var(--ligne); border-radius:8px; padding:10px; max-height:420px; overflow:auto; color: var(--texte);}
.petit { color:var(--discret); font-size:0.85rem; }
.grille.tdb td { vertical-align: middle; padding: 8px 10px; }
.grille.tdb small { display:block; color:var(--discret); font-size:0.78rem; }
.jauge { height:8px; border-radius:4px; background:#E3E8FB; overflow:hidden; min-width:120px; }
.jauge span { display:block; height:100%; border-radius:4px; background:var(--electrique); }
</style>
"""

# Compte administrateur : déclinaison foncée de la charte, pour qu'on reconnaisse la session au premier coup d'œil.
CSS_ADMIN = """
<style>
.stApp { background: linear-gradient(120deg, #EEF0FA 0%, #E2E7F7 50%, #CFEFE3 100%) fixed; }
section[data-testid="stSidebar"] { background: #0B0B45 !important; }
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(38,38,245,0.55); }
section[data-testid="stSidebar"] .logo-ias path[fill="#2626F5"] { fill: var(--menthe); }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #0E0E8C; }
div[data-testid="stMetric"] { box-shadow: 6px 6px 0 rgba(11,11,69,0.22); }
.grille th { background: #0B0B45; }
.bandeau-admin { display:inline-block; margin: 2px 0 8px; padding: 3px 10px; border-radius: 4px; background: var(--menthe);
        color: #0B0B45; font-weight: 800; font-size: 0.7rem; letter-spacing: 0.14em; }
</style>
"""


def marque(sous_titre: str = "Projet Centrale Lille", nom: str = "OR'CHESTRE") -> str:
    """Logo IAS + nom, comme en-tête des présentations."""
    return (f"<div class='marque'>{LOGO.replace(chr(10), '')}<div><div class='nom'>{nom}</div>"
            f"<div class='sous'>{sous_titre}</div></div></div>")


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
