# -*- coding: utf-8 -*-
"""
planning_vacations_v28.py
=========================

Planning du bloc opératoire (version 28) converti dans les structures de
`structures_communes.py` : Salle, Chirurgien, Creneau, Vacation.

Parité (définie dans structures_communes : TYPES_SEMAINE, type_semaine, planning_pour_semaine)
-----------------------------------------------------------------------------------------
Cycle de 4 semaines : impaire_1, paire, impaire_2, paire.
    "paire"      : toutes les semaines paires
    "impaire_1"  : une semaine impaire sur 2   (colonnes J et N du fichier)
    "impaire_2"  : l'autre semaine impaire     (colonnes K et O du fichier)

Le MODÈLE (CRENEAUX_MODELE, VACATIONS_MODELE) contient TOUTES les vacations ; chacune porte
`Vacation.semaines` (ex. ("paire",), ("impaire_1", "impaire_2"), les 3 types...).
Pour une semaine réelle :
    creneaux, vacations, chirurgiens = construire_semaine(lundi)
    # = planning_pour_semaine(CRENEAUX_MODELE, VACATIONS_MODELE, lundi) + chirurgiens de la semaine
Raccourcis par type : PLANNING[type] = (creneaux, vacations), CHIRURGIENS[type].
Les dates du modèle (semaine du 5/10/2026) ne servent que de repère ; les ids de vacation
sont ceux du modèle (stables d'une semaine à l'autre).

Conventions
-----------
  * Les vacations qui enjambent la pause repas (13h-13h30) sont coupées en deux
    (ex. 8h-17h30 -> 8h-13h + 13h30-17h30).
  * 1 vacation = 1 Creneau (même id) : les horaires ne sont pas des multiples de 2 h.
  * "URGENCE" et "LIBRE" sont des pseudo-chirurgiens (ids 900 et 901).
  * besoin_heures_semaine = somme des durées des vacations du praticien sur ce type de
    semaine (hors marge, hors pause).
  * salles_autorisees = salles où le praticien apparaît (tous types de semaine) ;
    salle_preferee = la plus fréquente.
  * Salle 1 : colonne vide dans le fichier -> salle créée mais sans vacation.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import date, time, timedelta
from pathlib import Path
from typing import Optional

# structures_communes.py partagé par tout le dépôt : dossier commun/
_COMMUN = str(Path(__file__).resolve().parents[1] / "commun")
if _COMMUN not in sys.path:
    sys.path.insert(0, _COMMUN)

from structures_communes import (LUNDI_REFERENCE_CYCLE, TYPES_SEMAINE, Chirurgien, Creneau,  # noqa: E402
                                 InstanceNiveau2, Salle, Vacation, generer_patients_etude, planning_pour_semaine,
                                 type_semaine)

# =============================================================================
# PARAMÈTRES
# =============================================================================

SEMAINES = TYPES_SEMAINE

# Un lundi de chaque type de semaine, déduit du cycle (LUNDI_REFERENCE_CYCLE dans structures_communes).
LUNDI_REFERENCE = {
    "impaire_1": LUNDI_REFERENCE_CYCLE,
    "paire": LUNDI_REFERENCE_CYCLE + timedelta(days=7),
    "impaire_2": LUNDI_REFERENCE_CYCLE + timedelta(days=14),
}

PAUSE_DEBUT, PAUSE_FIN = time(13, 0), time(13, 30)

ID_URGENCE, ID_LIBRE = 900, 901
NOM_URGENCE, NOM_LIBRE = "URGENCE", "LIBRE"

SALLES = {i: Salle(i, f"Salle {i}") for i in range(1, 6)}

# =============================================================================
# DONNÉES : (jour 0=lundi..4=vendredi, salle, praticien, début, fin, semaines)
# =============================================================================

TOUTES = SEMAINES
PAIRE = ("paire",)
IMPAIRES = ("impaire_1", "impaire_2")
I1 = ("impaire_1",)
I2 = ("impaire_2",)

BLOCS = [
    # ---- Lundi
    (0, 2, "JT",     "7:45", "17:30", TOUTES),
    (0, 3, "SR",     "8:00", "17:30", PAIRE),
    (0, 3, "GA",     "8:00", "13:00", I1),
    (0, 3, "MT",     "13:30", "17:30", I1),
    (0, 3, "GHREA",  "8:00", "10:00", I2),
    (0, 3, "DEVOS",  "10:00", "15:30", I2),
    (0, 4, "GA",     "8:00", "13:00", PAIRE),
    (0, 4, NOM_URGENCE, "13:30", "15:30", PAIRE),
    (0, 4, "TDO/BS", "8:00", "10:00", I1),
    (0, 4, "DS",     "10:00", "15:30", I1),
    (0, 4, "RL",     "8:00", "13:00", I2),
    (0, 4, "MT",     "13:30", "17:30", I2),
    (0, 5, "FN",     "8:00", "15:30", TOUTES),      # ? le fichier affiche FN à partir de 10h
    # ---- Mardi
    (1, 2, "JT",     "7:45", "15:30", PAIRE),
    (1, 2, "JT",     "7:45", "17:30", IMPAIRES),
    (1, 3, "TR",     "8:00", "13:00", TOUTES),
    (1, 3, "MT",     "13:30", "17:30", PAIRE),
    (1, 3, NOM_URGENCE, "13:30", "15:30", IMPAIRES),
    (1, 4, "CT",     "8:00", "15:30", TOUTES),
    (1, 5, "MO",     "8:00", "17:30", TOUTES),
    # ---- Mercredi
    (2, 2, "CL",     "7:45", "17:30", TOUTES),
    (2, 3, "DE",     "8:00", "17:30", TOUTES),
    (2, 4, "DN",     "8:00", "13:00", TOUTES),
    (2, 4, NOM_URGENCE, "13:30", "15:30", TOUTES),
    (2, 5, "MT",     "8:00", "13:00", PAIRE),
    (2, 5, NOM_URGENCE, "13:30", "15:30", PAIRE),
    (2, 5, "JE",     "8:00", "15:30", IMPAIRES),
    # ---- Jeudi
    (3, 2, "DE",     "7:45", "17:30", TOUTES),
    (3, 3, "SR",     "8:00", "15:30", TOUTES),      # ? TVO du fichier = 9,5 h (jusqu'à 17h30)
    (3, 4, "CT",     "8:00", "15:30", TOUTES),
    (3, 5, "LZ",     "8:00", "17:30", TOUTES),
    # ---- Vendredi
    (4, 2, "CL",     "7:45", "13:00", TOUTES),
    (4, 2, NOM_URGENCE, "13:30", "15:30", TOUTES),
    (4, 3, "CU",     "8:00", "13:00", TOUTES),
    (4, 3, "MT",     "13:30", "15:30", TOUTES),
    (4, 4, "HA",     "8:00", "13:00", PAIRE),
    (4, 4, "FP",     "13:30", "17:30", PAIRE),
    (4, 4, "SM",     "8:00", "17:30", IMPAIRES),
    (4, 5, "LR",     "8:00", "13:00", TOUTES),
    (4, 5, NOM_LIBRE, "13:30", "17:30", TOUTES),
]


# =============================================================================
# CONSTRUCTION
# =============================================================================

def _t(texte: str) -> time:
    h, m = texte.split(":")
    return time(int(h), int(m))


def _decouper(debut: time, fin: time) -> list[tuple[time, time]]:
    """Coupe une plage qui enjambe la pause repas en deux vacations."""
    if debut < PAUSE_DEBUT and fin > PAUSE_FIN:
        return [(debut, PAUSE_DEBUT), (PAUSE_FIN, fin)]
    return [(debut, fin)]


def _ids_praticiens() -> dict[str, int]:
    noms = sorted({b[2] for b in BLOCS} - {NOM_URGENCE, NOM_LIBRE})
    ids = {nom: i for i, nom in enumerate(noms, start=1)}
    ids[NOM_URGENCE], ids[NOM_LIBRE] = ID_URGENCE, ID_LIBRE
    return ids


ID_PAR_NOM = _ids_praticiens()
NOM_PAR_ID = {i: n for n, i in ID_PAR_NOM.items()}


def _construire_modele(blocs: Optional[list] = None) -> tuple[dict[int, Creneau], dict[int, Vacation]]:
    """Modèle : une Vacation par plage (pause repas coupée), avec ses types de semaine."""
    groupes: dict[tuple, set] = {}
    for jour, salle, nom, deb, fin, semaines in (BLOCS if blocs is None else blocs):
        for d, f in _decouper(_t(deb), _t(fin)):
            groupes.setdefault((jour, salle, d, f, ID_PAR_NOM[nom]), set()).update(semaines)
    creneaux, vacations = {}, {}
    for vid, (cle, sem) in enumerate(sorted(groupes.items()), start=1):
        jour, salle, d, f, pid = cle
        j = LUNDI_REFERENCE_CYCLE + timedelta(days=jour)
        creneaux[vid] = Creneau(vid, j, d, f)
        vacations[vid] = Vacation(vid, pid, salle, j, d, f, (vid,),
                                  semaines=tuple(t for t in TYPES_SEMAINE if t in sem))
    return creneaux, vacations


CRENEAUX_MODELE, VACATIONS_MODELE = _construire_modele()


def _salles_et_preference(modeles: Optional[list] = None) -> dict[int, tuple[tuple[int, ...], Optional[int]]]:
    """Par praticien : (salles autorisées, salle préférée = la plus fréquente, tous types de semaine)."""
    freq: dict[int, Counter] = defaultdict(Counter)
    minutes: dict[int, Counter] = defaultdict(Counter)
    for v in (v for vm in (modeles or [VACATIONS_MODELE]) for v in vm.values()):
        freq[v.chirurgien_id][v.salle_id] += len(v.semaines)
        minutes[v.chirurgien_id][v.salle_id] += v.duree_minutes * len(v.semaines)
    res = {}
    for pid, c in freq.items():
        pref = min(c, key=lambda s: (-c[s], -minutes[pid][s], s))
        res[pid] = (tuple(sorted(c)), pref)
    return res


_SALLES_PREF = _salles_et_preference()


def chirurgiens_de(vacations: dict[int, Vacation]) -> dict[int, Chirurgien]:
    """Chirurgiens d'une semaine : besoin_heures_semaine = somme de leurs vacations (hors marge, hors pause)."""
    minutes: Counter = Counter()
    for v in vacations.values():
        minutes[v.chirurgien_id] += v.duree_minutes
    return {pid: Chirurgien(pid, NOM_PAR_ID[pid], mn / 60, *_SALLES_PREF[pid])
            for pid, mn in sorted(minutes.items())}


def construire_semaine(lundi: date) -> tuple[dict[int, Creneau], dict[int, Vacation], dict[int, Chirurgien]]:
    """Planning d'une semaine réelle : le type (paire / impaire_1 / impaire_2) est déduit de la date, le modèle
    est la version du planning en vigueur cette semaine-là (voir definir_versions)."""
    creneaux_modele, vacations_modele = modele_pour(lundi)
    creneaux, vacations = planning_pour_semaine(creneaux_modele, vacations_modele, lundi)
    return creneaux, vacations, chirurgiens_de(vacations)


# =============================================================================
# VERSIONS DU PLANNING (modifications décidées par l'administrateur)
# =============================================================================
# Le planning est FIXE : il se répète à l'identique de semaine en semaine (cycle paire / impaire A / impaire B).
# Une modification crée une VERSION qui s'applique à partir d'un lundi (date d'effet) ; les semaines antérieures
# gardent la version précédente, le passé n'est donc jamais réécrit. Les ids des praticiens existants ne changent
# jamais (un nouveau praticien reçoit le premier id libre) ; les ids de vacation restent < 100 (le SMA décale les
# ids de 100 par semaine).

MAX_VACATIONS_MODELE = 99
_VERSIONS: list[tuple[date, list, dict[int, Creneau], dict[int, Vacation]]] = []   # triées par date d'effet


def ajouter_praticiens(noms, ids_connus: Optional[dict[str, int]] = None) -> dict[str, int]:
    """Enregistre les praticiens inconnus : id déjà attribué (`ids_connus`, à conserver par l'appelant) ou premier
    id libre après les existants. Renvoie les ids des praticiens ajoutés."""
    ajoutes = {}
    for nom in sorted(set(noms) - set(ID_PAR_NOM)):
        nouvel_id = (ids_connus or {}).get(nom) or max(i for i in ID_PAR_NOM.values() if i < ID_URGENCE) + 1
        if nouvel_id >= ID_URGENCE or nouvel_id in NOM_PAR_ID:
            raise ValueError(f"id de praticien indisponible pour {nom}")
        ID_PAR_NOM[nom] = nouvel_id
        NOM_PAR_ID[nouvel_id] = nom
        ajoutes[nom] = nouvel_id
    return ajoutes


def verifier_blocs(blocs: list) -> list[str]:
    """Erreurs bloquantes d'une version : horaires, jour, salle, types de semaine, conflits salle / praticien."""
    erreurs = []
    for k, (jour, salle, nom, deb, fin, semaines) in enumerate(blocs, start=1):
        try:
            d, f = _t(deb), _t(fin)
        except (ValueError, AttributeError):
            erreurs.append(f"ligne {k} : horaire invalide ({deb} – {fin}), format attendu 8:00")
            continue
        if not d < f:
            erreurs.append(f"ligne {k} : l'heure de fin doit suivre l'heure de début")
        if jour not in range(5) or salle not in SALLES:
            erreurs.append(f"ligne {k} : jour ou salle invalide")
        if not nom:
            erreurs.append(f"ligne {k} : praticien manquant")
        if not semaines:
            erreurs.append(f"ligne {k} : aucun type de semaine coché")
    if erreurs:
        return erreurs
    ids, noms = dict(ID_PAR_NOM), dict(NOM_PAR_ID)          # vérification sans effet sur les praticiens connus
    try:
        ajouter_praticiens(b[2] for b in blocs)
        _, vacations = _construire_modele(blocs)
        if len(vacations) > MAX_VACATIONS_MODELE:
            return [f"{len(vacations)} vacations : {MAX_VACATIONS_MODELE} au maximum"]
        return _conflits(vacations)
    finally:
        ID_PAR_NOM.clear(); ID_PAR_NOM.update(ids)
        NOM_PAR_ID.clear(); NOM_PAR_ID.update(noms)


def _conflits(vacations: dict[int, Vacation]) -> list[str]:
    erreurs = []
    jours = ("lundi", "mardi", "mercredi", "jeudi", "vendredi")
    for ts in TYPES_SEMAINE:
        liste = [v for v in vacations.values() if ts in v.semaines]
        for i, a in enumerate(liste):
            for b in liste[i + 1:]:
                if a.jour != b.jour or not (a.heure_debut < b.heure_fin and b.heure_debut < a.heure_fin):
                    continue
                quand = f"{jours[a.jour.weekday()]} ({ts.replace('_1', ' A').replace('_2', ' B')})"
                if a.salle_id == b.salle_id:
                    erreurs.append(f"Salle {a.salle_id} {quand} : {NOM_PAR_ID[a.chirurgien_id]} et "
                                   f"{NOM_PAR_ID[b.chirurgien_id]} se chevauchent")
                if a.chirurgien_id == b.chirurgien_id and a.chirurgien_id not in (ID_URGENCE, ID_LIBRE):
                    erreurs.append(f"{NOM_PAR_ID[a.chirurgien_id]} dans deux salles en même temps {quand}")
    return erreurs


def definir_versions(versions: list[tuple[date, list]], ids_praticiens: Optional[dict[str, int]] = None) -> dict[str, int]:
    """Remplace les versions du planning : [(lundi d'effet, blocs au format BLOCS), ...]. `ids_praticiens` : ids déjà
    attribués aux praticiens ajoutés (stables d'un lancement à l'autre). Renvoie tous les ids attribués."""
    global _VERSIONS, _SALLES_PREF
    res, attribues = [], dict(ids_praticiens or {})
    for effet, blocs in sorted(versions, key=lambda x: x[0]):
        blocs = [tuple(b[:5]) + (tuple(b[5]),) for b in blocs]
        attribues.update(ajouter_praticiens((b[2] for b in blocs), attribues))
        creneaux, vacations = _construire_modele(blocs)
        res.append((effet - timedelta(days=effet.weekday()), blocs, creneaux, vacations))
    _VERSIONS = res
    _SALLES_PREF = _salles_et_preference([VACATIONS_MODELE] + [v[3] for v in res])
    return attribues


def modele_pour(lundi: date) -> tuple[dict[int, Creneau], dict[int, Vacation]]:
    lundi = lundi - timedelta(days=lundi.weekday())
    for effet, _, creneaux, vacations in reversed(_VERSIONS):
        if effet <= lundi:
            return creneaux, vacations
    return CRENEAUX_MODELE, VACATIONS_MODELE


def blocs_pour(lundi: date) -> list:
    """Blocs (format BLOCS) de la version en vigueur la semaine du `lundi`."""
    lundi = lundi - timedelta(days=lundi.weekday())
    for effet, blocs, _, _ in reversed(_VERSIONS):
        if effet <= lundi:
            return list(blocs)
    return list(BLOCS)


def verifier_semaine(lundi: date) -> list[str]:
    """Erreurs de cohérence : salle ou praticien (hors URGENCE/LIBRE) en double sur une même plage."""
    _, vacs, _ = construire_semaine(lundi)
    ts = type_semaine(lundi)
    erreurs = []
    liste = list(vacs.values())
    for i, a in enumerate(liste):
        for b in liste[i + 1:]:
            if a.jour != b.jour or not (a.heure_debut < b.heure_fin and b.heure_debut < a.heure_fin):
                continue
            if a.salle_id == b.salle_id:
                erreurs.append(f"[{ts}] conflit salle {a.salle_id} {a.jour} : "
                               f"{NOM_PAR_ID[a.chirurgien_id]} / {NOM_PAR_ID[b.chirurgien_id]}")
            if a.chirurgien_id == b.chirurgien_id and a.chirurgien_id not in (ID_URGENCE, ID_LIBRE):
                erreurs.append(f"[{ts}] {NOM_PAR_ID[a.chirurgien_id]} dans 2 salles {a.jour}")
    return erreurs


def instance_niveau2(lundi: date, patients: Optional[dict] = None) -> InstanceNiveau2:
    """
    Instance prête pour Tabou / AGS / Recuit simulé : toutes les vacations de la semaine du `lundi`
    + les patients (par défaut : patients fictifs du générateur de l'étude).
    """
    _, vacations, chirurgiens = construire_semaine(lundi)
    if patients is None:
        patients = generer_patients_etude(vacations)
    return InstanceNiveau2(patients, vacations, noms_chirurgiens={i: c.nom for i, c in chirurgiens.items()},
                           nom=f"bloc_{type_semaine(lundi)}_{lundi}")


PLANNING = {t: construire_semaine(LUNDI_REFERENCE[t])[:2] for t in SEMAINES}      # (creneaux, vacations)
CHIRURGIENS = {t: construire_semaine(LUNDI_REFERENCE[t])[2] for t in SEMAINES}


if __name__ == "__main__":
    from structures_communes import JOURS_FR
    for t in SEMAINES:
        _, vacations = PLANNING[t]
        print(f"\n=== Semaine {t} (ex. lundi {LUNDI_REFERENCE[t]}) : {len(vacations)} vacations ===")
        for v in vacations.values():
            print(f"{JOURS_FR[v.jour.weekday()]:<9} Salle {v.salle_id}  "
                  f"{v.heure_debut:%Hh%M}-{v.heure_fin:%Hh%M}  {NOM_PAR_ID[v.chirurgien_id]}")
        print("Erreurs :", verifier_semaine(LUNDI_REFERENCE[t]) or "aucune")
