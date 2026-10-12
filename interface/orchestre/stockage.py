# -*- coding: utf-8 -*-
"""
Stockage local (SQLite) et mesures de protection des données (RGPD / recommandations CNIL).

* Pseudonymisation : chaque patient reçoit un code (ex. PAT-26-0007). Le nom n'est jamais demandé ;
  la seule donnée directement identifiante acceptée est une référence de dossier (IPP), facultative,
  CHIFFRÉE en base (Fernet / AES-128-CBC + HMAC) avec une clé stockée hors de la base.
* Minimisation : seules les variables utilisées par le modèle et par la programmation sont collectées
  (âge et non date de naissance, pas de CIM/CCAM associés que le modèle n'utilise pas).
* Traçabilité : chaque consultation, création, modification, export ou suppression est journalisée
  (qui, quand, quoi) dans journal_acces.
* Conservation limitée : purge automatique des données patient N jours après l'intervention.
* Comptes nominatifs, mots de passe hachés (PBKDF2-SHA256, 310 000 itérations, sel aléatoire).
* Événementiel : la base garde la liste des événements (inscriptions, urgences, pannes, annulations),
  rejoués par le SMA. Supprimer un patient = supprimer ses événements (droit à l'effacement).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import chemins

FICHIER_BASE = chemins.DOSSIER_DONNEES / "orchestre.db"
FICHIER_CLE = chemins.DOSSIER_DONNEES / "cle_chiffrement.key"
ITERATIONS_PBKDF2 = 310_000
DUREE_CONSERVATION_JOURS_DEFAUT = 30          # après la date d'intervention
DUREE_JOURNAL_JOURS = 183                     # traces conservées 6 mois (recommandation CNIL)
ROLES = {"chirurgien": "Chirurgien", "regulation": "Cadre de bloc / régulation", "admin": "Administrateur"}

_verrou = threading.Lock()
FUSEAU = ZoneInfo("Europe/Paris")


def horodatage() -> str:
    """Heure légale française (indépendante du fuseau du serveur)."""
    return datetime.now(FUSEAU).replace(tzinfo=None).isoformat(timespec="seconds")

SCHEMA = """
CREATE TABLE IF NOT EXISTS parametres (cle TEXT PRIMARY KEY, valeur TEXT);
CREATE TABLE IF NOT EXISTS utilisateurs (
    login TEXT PRIMARY KEY, nom_affiche TEXT, role TEXT, praticien TEXT,
    sel TEXT, empreinte TEXT, actif INTEGER DEFAULT 1, doit_changer INTEGER DEFAULT 1, cree_le TEXT);
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pseudo TEXT UNIQUE, ref_chiffree BLOB,
    praticien TEXT, entrees TEXT, prediction TEXT, valide TEXT, statut TEXT,
    information_patient INTEGER, cree_par TEXT, cree_le TEXT, date_intervention TEXT, maj_le TEXT);
CREATE TABLE IF NOT EXISTS evenements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, heure TEXT, type TEXT, contenu TEXT,
    patient_id INTEGER, auteur TEXT, cree_le TEXT);
CREATE TABLE IF NOT EXISTS journal_acces (
    id INTEGER PRIMARY KEY AUTOINCREMENT, horodatage TEXT, utilisateur TEXT, role TEXT,
    action TEXT, objet TEXT);
"""


# =============================================================================
# Connexion
# =============================================================================

@contextmanager
def connexion():
    with _verrou:
        con = sqlite3.connect(FICHIER_BASE)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def initialiser() -> None:
    with connexion() as con:
        con.executescript(SCHEMA)
    try:
        os.chmod(FICHIER_BASE, 0o600)
    except OSError:
        pass


# =============================================================================
# Chiffrement de la référence de dossier
# =============================================================================

def _fernet():
    from cryptography.fernet import Fernet
    cle = os.environ.get("ORCHESTRE_CLE")
    if cle:
        return Fernet(cle.encode())
    if not FICHIER_CLE.exists():
        FICHIER_CLE.write_bytes(Fernet.generate_key())
        try:
            os.chmod(FICHIER_CLE, 0o600)
        except OSError:
            pass
    return Fernet(FICHIER_CLE.read_bytes())


def chiffrer(texte: str) -> Optional[bytes]:
    return _fernet().encrypt(texte.encode()) if texte else None


def dechiffrer(donnee: Optional[bytes]) -> str:
    if not donnee:
        return ""
    try:
        return _fernet().decrypt(donnee).decode()
    except Exception:
        return "(clé de chiffrement invalide)"


# =============================================================================
# Paramètres
# =============================================================================

def lire_parametre(cle: str, defaut: Any = None) -> Any:
    with connexion() as con:
        r = con.execute("SELECT valeur FROM parametres WHERE cle=?", (cle,)).fetchone()
    return json.loads(r["valeur"]) if r else defaut


def ecrire_parametre(cle: str, valeur: Any) -> None:
    with connexion() as con:
        con.execute("INSERT OR REPLACE INTO parametres VALUES (?, ?)", (cle, json.dumps(valeur, default=str)))


# =============================================================================
# Utilisateurs
# =============================================================================

def _empreinte(mot_de_passe: str, sel: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), bytes.fromhex(sel), ITERATIONS_PBKDF2).hex()


def creer_utilisateur(login: str, mot_de_passe: str, role: str, nom_affiche: str, praticien: str = "",
                      doit_changer: bool = True) -> None:
    if role not in ROLES:
        raise ValueError(role)
    sel = secrets.token_hex(16)
    with connexion() as con:
        con.execute("INSERT OR REPLACE INTO utilisateurs VALUES (?,?,?,?,?,?,1,?,?)",
                    (login, nom_affiche, role, praticien, sel, _empreinte(mot_de_passe, sel), int(doit_changer),
                     horodatage()))


def verifier_mot_de_passe(login: str, mot_de_passe: str) -> Optional[dict]:
    with connexion() as con:
        r = con.execute("SELECT * FROM utilisateurs WHERE login=? AND actif=1", (login,)).fetchone()
    if r is None:
        _empreinte(mot_de_passe, "00" * 16)                 # temps constant : pas d'énumération des comptes
        return None
    if not hmac.compare_digest(_empreinte(mot_de_passe, r["sel"]), r["empreinte"]):
        return None
    return dict(r)


def changer_mot_de_passe(login: str, nouveau: str) -> None:
    sel = secrets.token_hex(16)
    with connexion() as con:
        con.execute("UPDATE utilisateurs SET sel=?, empreinte=?, doit_changer=0 WHERE login=?",
                    (sel, _empreinte(nouveau, sel), login))


def mot_de_passe_robuste(mdp: str) -> list[str]:
    """Recommandation CNIL (délibération 2022-100) : 12 caractères min. avec 4 types de caractères."""
    pb = []
    if len(mdp) < 12:
        pb.append("au moins 12 caractères")
    for test, nom in ((str.islower, "une minuscule"), (str.isupper, "une majuscule"), (str.isdigit, "un chiffre")):
        if not any(test(c) for c in mdp):
            pb.append(nom)
    if all(c.isalnum() for c in mdp):
        pb.append("un caractère spécial")
    return pb


def lister_utilisateurs() -> list[dict]:
    with connexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT login, nom_affiche, role, praticien, actif, doit_changer, cree_le FROM utilisateurs ORDER BY role, login")]


def activer_utilisateur(login: str, actif: bool) -> None:
    with connexion() as con:
        con.execute("UPDATE utilisateurs SET actif=? WHERE login=?", (int(actif), login))


def comptes_de_demonstration() -> dict[str, str]:
    """Crée des comptes de démonstration au premier lancement (mot de passe à changer à la 1re connexion)."""
    if lister_utilisateurs():
        return {}
    comptes = {}
    for login, role, nom, prat in (("admin", "admin", "Administrateur", ""),
                                   ("regulation", "regulation", "Cadre de bloc", ""),
                                   ("dr.ct", "chirurgien", "Dr CT", "CT"),
                                   ("dr.cl", "chirurgien", "Dr CL", "CL"),
                                   ("dr.lz", "chirurgien", "Dr LZ", "LZ")):
        mdp = "Demo-" + secrets.token_urlsafe(9)
        creer_utilisateur(login, mdp, role, nom, prat, doit_changer=True)
        comptes[login] = mdp
    fichier = chemins.DOSSIER_DONNEES / "comptes_demo.txt"
    fichier.write_text("Comptes de démonstration (mot de passe à changer à la première connexion)\n"
                       + "\n".join(f"{l} : {m}" for l, m in comptes.items()) + "\n", encoding="utf-8")
    try:
        os.chmod(fichier, 0o600)
    except OSError:
        pass
    return comptes


# =============================================================================
# Journal des accès (traçabilité)
# =============================================================================

def tracer(utilisateur: str, role: str, action: str, objet: str = "") -> None:
    with connexion() as con:
        con.execute("INSERT INTO journal_acces (horodatage, utilisateur, role, action, objet) VALUES (?,?,?,?,?)",
                    (horodatage(), utilisateur, role, action, objet))


def echecs_recents(login: str, minutes: int = 15) -> int:
    """Nombre d'échecs de connexion récents pour un identifiant (blocage temporaire au-delà de 5)."""
    depuis = (datetime.fromisoformat(horodatage()) - timedelta(minutes=minutes)).isoformat()
    with connexion() as con:
        return con.execute("SELECT COUNT(*) FROM journal_acces WHERE utilisateur=? AND action='échec de connexion' "
                           "AND horodatage >= ?", (login, depuis)).fetchone()[0]


def lire_journal(limite: int = 500) -> list[dict]:
    with connexion() as con:
        return [dict(r) for r in con.execute("SELECT * FROM journal_acces ORDER BY id DESC LIMIT ?", (limite,))]


# =============================================================================
# Patients (pseudonymisés)
# =============================================================================

def _nouveau_pseudo(con) -> str:
    n = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0] + 1
    while True:
        pseudo = f"PAT-{horodatage()[2:4]}-{n:04d}"
        if not con.execute("SELECT 1 FROM patients WHERE pseudo=?", (pseudo,)).fetchone():
            return pseudo
        n += 1


def creer_patient(*, praticien: str, entrees: dict, prediction: dict, valide: dict, reference: str,
                  information_patient: bool, auteur: str, statut: str = "à programmer") -> dict:
    maintenant = horodatage()
    with connexion() as con:
        pseudo = _nouveau_pseudo(con)
        cur = con.execute(
            "INSERT INTO patients (pseudo, ref_chiffree, praticien, entrees, prediction, valide, statut, "
            "information_patient, cree_par, cree_le, maj_le) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pseudo, chiffrer(reference.strip()), praticien, json.dumps(entrees, default=str),
             json.dumps(prediction, default=str), json.dumps(valide, default=str), statut,
             int(information_patient), auteur, maintenant, maintenant))
        pid = cur.lastrowid
    return {"id": pid, "pseudo": pseudo}


def _patient(r) -> dict:
    d = dict(r)
    for k in ("entrees", "prediction", "valide"):
        d[k] = json.loads(d[k]) if d[k] else {}
    d["a_reference"] = bool(d.pop("ref_chiffree"))
    return d


def lister_patients(praticien: Optional[str] = None) -> list[dict]:
    with connexion() as con:
        if praticien:
            rows = con.execute("SELECT * FROM patients WHERE praticien=? ORDER BY id DESC", (praticien,))
        else:
            rows = con.execute("SELECT * FROM patients ORDER BY id DESC")
        return [_patient(r) for r in rows]


def patient(pid: int) -> Optional[dict]:
    with connexion() as con:
        r = con.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    return _patient(r) if r else None


def reference_dossier(pid: int) -> str:
    with connexion() as con:
        r = con.execute("SELECT ref_chiffree FROM patients WHERE id=?", (pid,)).fetchone()
    return dechiffrer(r["ref_chiffree"]) if r else ""


def maj_patient(pid: int, **champs) -> None:
    champs["maj_le"] = horodatage()
    for k in ("entrees", "prediction", "valide"):
        if k in champs:
            champs[k] = json.dumps(champs[k], default=str)
    cles = ", ".join(f"{k}=?" for k in champs)
    with connexion() as con:
        con.execute(f"UPDATE patients SET {cles} WHERE id=?", (*champs.values(), pid))


def supprimer_patient(pid: int) -> None:
    """Droit à l'effacement : fiche ET événements (le SMA rejoue sans ce patient)."""
    with connexion() as con:
        con.execute("DELETE FROM evenements WHERE patient_id=?", (pid,))
        con.execute("DELETE FROM patients WHERE id=?", (pid,))


def exporter_patient(pid: int) -> dict:
    """Droit d'accès / portabilité : toutes les données détenues sur un patient."""
    p = patient(pid)
    if p is None:
        return {}
    p["reference_dossier"] = reference_dossier(pid)
    p["evenements"] = [e for e in lister_evenements() if e["patient_id"] == pid]
    return p


def purger(duree_jours: int) -> list[str]:
    """Supprime les patients dont l'intervention date de plus de `duree_jours` jours et les traces trop anciennes."""
    limite = (datetime.fromisoformat(horodatage()).date() - timedelta(days=duree_jours)).isoformat()
    with connexion() as con:
        rows = con.execute("SELECT id, pseudo FROM patients WHERE date_intervention IS NOT NULL "
                           "AND date_intervention < ?", (limite,)).fetchall()
        for r in rows:
            con.execute("DELETE FROM evenements WHERE patient_id=?", (r["id"],))
            con.execute("DELETE FROM patients WHERE id=?", (r["id"],))
        lim_journal = (datetime.fromisoformat(horodatage()) - timedelta(days=DUREE_JOURNAL_JOURS)).isoformat()
        con.execute("DELETE FROM journal_acces WHERE horodatage < ?", (lim_journal,))
    return [r["pseudo"] for r in rows]


# =============================================================================
# Événements (rejoués par le SMA)
# =============================================================================

def ajouter_evenement(heure: datetime, type_: str, contenu: dict, auteur: str, patient_id: Optional[int] = None) -> int:
    with connexion() as con:
        cur = con.execute("INSERT INTO evenements (heure, type, contenu, patient_id, auteur, cree_le) VALUES (?,?,?,?,?,?)",
                          (heure.isoformat(timespec="seconds"), type_, json.dumps(contenu, default=str), patient_id,
                           auteur, horodatage()))
        return cur.lastrowid


def lister_evenements() -> list[dict]:
    with connexion() as con:
        rows = con.execute("SELECT * FROM evenements ORDER BY heure, id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["contenu"] = json.loads(d["contenu"])
        d["heure"] = datetime.fromisoformat(d["heure"])
        out.append(d)
    return out


def supprimer_evenement(eid: int) -> None:
    with connexion() as con:
        con.execute("DELETE FROM evenements WHERE id=?", (eid,))


def vider_evenements() -> None:
    with connexion() as con:
        con.execute("DELETE FROM evenements")
        con.execute("UPDATE patients SET statut='à programmer', date_intervention=NULL")


def empreinte_evenements() -> str:
    """Change dès qu'un événement est ajouté / supprimé : clé du cache de la simulation."""
    with connexion() as con:
        rows = con.execute("SELECT id, heure, type, contenu FROM evenements ORDER BY id").fetchall()
    return hashlib.sha256(json.dumps([tuple(r) for r in rows]).encode()).hexdigest()[:16]
