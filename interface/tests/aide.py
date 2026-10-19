# -*- coding: utf-8 -*-
"""Outils partagés par les tests : patients et événements au format enregistré par le site, contrôles communs."""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestre import sma_service as S  # noqa: E402

import structures_communes as SC  # noqa: E402

LUNDI = date(2026, 10, 12)                     # premier lundi du programme de test (semaine paire)
MARDI = LUNDI + timedelta(days=1)
MATIN = datetime.combine(LUNDI, time(6, 30))   # avant l'ouverture du bloc : aucune intervention commencée


def patient(k: int, chirurgien: str = "CT", duree: int = 60, *, ambulatoire: bool = True, priorite: int = 2,
            nuits_post_op: int = 0, date_min: date = LUNDI) -> SC.Patient:
    """Patient de consultation n° k (pid du site : DECALAGE_PID_CONSULTATION + 9000 + k)."""
    return SC.Patient(id=S.pid_consultation(9000 + k), chirurgien_id=S.id_chirurgien(chirurgien), duree_bloc=duree,
                      ambulatoire=ambulatoire, nuits_post_op=0 if ambulatoire else nuits_post_op, priorite=priorite,
                      date_min=date_min, nom=f"TEST-{k}", specialite=S.SMA.specialite_de(chirurgien))


def numero(p: SC.Patient) -> int:
    return p.id - S.DECALAGE_PID_CONSULTATION - 9000


def _evenement(heure: datetime, type_: str, contenu: dict) -> dict:
    return {"id": None, "heure": heure, "type": type_, "contenu": contenu, "auteur": "test", "patient_id": None}


def inscription(heure: datetime, p: SC.Patient, *, confrere: bool = False, proposition: Optional[dict] = None) -> dict:
    return _evenement(heure, "inscription", {
        "patient": S.patient_vers_dict(p), "jour_min": (p.date_min or LUNDI).isoformat(),
        "chirurgiens": S.chirurgiens_possibles(p, confrere),
        "salle_id": proposition["salle_id"] if proposition else None,
        "fenetre_id": proposition["fenetre_id"] if proposition else None})


def urgence(heure: datetime, n: int, chirurgien: str = "CT", gravite: str = "urgente", duree: int = 60,
            ambulatoire: bool = False) -> dict:
    p = S.patient_urgent(n, chirurgien, duree, ambulatoire=ambulatoire, nuits_post_op=0 if ambulatoire else 2)
    return _evenement(heure, "urgence", {"patient": S.patient_vers_dict(p), "gravite": gravite})


def absence(heure: datetime, chirurgien: str, du: date, au: date, motif: str = "Vacances") -> dict:
    return _evenement(heure, "absence", {"praticien": chirurgien, "du": du.isoformat(), "au": au.isoformat(),
                                         "motif": motif, "precision": ""})


def panne(heure: datetime, fin: datetime, ascenseur: str = "ML1") -> dict:
    return _evenement(heure, "panne", {"ascenseur": ascenseur, "fin_estimee": fin.isoformat()})


def fin_panne(heure: datetime, ascenseur: str = "ML1") -> dict:
    return _evenement(heure, "fin_panne", {"ascenseur": ascenseur})


def annulation(heure: datetime, pid: int) -> dict:
    return _evenement(heure, "annulation", {"pid": pid, "nom": f"P{pid}", "motif": "test"})


def reoptimisation(heure: datetime, contenu: dict) -> dict:
    return _evenement(heure, "reoptimisation", contenu)


def etat(sim: S.Simulation) -> dict:
    """Instantané comparable du programme (pid -> statut, salle, début, chirurgien)."""
    return S.etat_programme(sim.modele)


def coherent(sim: S.Simulation) -> list[str]:
    """Erreurs du contrôle indépendant du SMA (salles, chirurgiens, heures du planning, agendas, séjours)."""
    return sim.modele.verifier_coherence()


def intervention_de(sim: S.Simulation, p: SC.Patient):
    return sim.intervention(p.id)
