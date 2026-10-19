# -*- coding: utf-8 -*-
"""
Étude de saturation du bloc : combien de patients faut-il pour remplir l'horizon ?

    python interface/tests/saturation.py                  # 4 semaines, capacités du site
    python interface/tests/saturation.py --semaines 2 --lits 42 --reserve 4 --places 18

Méthode
-------
* Programme VIDE (aucun patient de démonstration), planning des vacations réel (v28) et capacités du site.
* N patients inscrits un par un, comme en consultation (date au plus tôt = premier lundi, priorité 2, sans
  confrère sauf --confrere). Durée au bloc, ambulatoire / hospitalisation et nuits avant / après : tirées dans les
  séjours RÉELS de machine_learning/donnees_hospitalieres.csv. Chirurgien : tiré au prorata de son temps de vacation
  (la demande a la forme de l'offre).
* Le SMA place chaque patient exactement comme sur le site (appel d'offres, agents Chirurgien et Hébergement).
  Les patients arrivent dans l'ordre et ne se déplacent pas entre eux : UN seul passage donne la courbe
  d'occupation en fonction du nombre de patients.

Sorties : tableau dans la console, interface/tests/resultats/saturation.md et saturation_courbe.csv.
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import time as chrono
import warnings
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)

from orchestre import chemins, ml  # noqa: E402
from orchestre import programme as P  # noqa: E402
from orchestre import sma_service as S  # noqa: E402

import sma_urgences as SMA  # noqa: E402
import structures_communes as SC  # noqa: E402
from parametres import GRAINE_SATURATION  # noqa: E402

LUNDI_DEFAUT = date(2026, 10, 12)
DOSSIER_RESULTATS = Path(__file__).resolve().parent / "resultats"


@dataclass
class Resultat:
    semaines: int
    hebergement: SC.ParametresHebergement
    n_patients: int
    minutes_vacation: float                 # temps de vacation des chirurgiens sur l'horizon (hors URGENCES / LIBRE)
    minutes_utiles: float                   # capacité utile (marge de 10 % gardée pour les aléas)
    places_dans_horizon: int                # patients opérés dans l'horizon
    premier_debordement: Optional[int]      # rang du premier patient placé APRÈS l'horizon (un chirurgien saturé)
    en_attente: int
    occupation_finale_pct: float            # minutes programmées / temps de vacation
    occupation_utile_pct: float             # minutes programmées / capacité utile
    pic_lits: int
    jours_lits_pleins: int
    pic_places: int
    jours_places_pleines: int
    debordes_hospitalises_pct: float        # part d'hospitalisés parmi les patients débordés
    seuils: dict[int, Optional[int]]        # % de la capacité utile -> patients inscrits pour l'atteindre
    capacite_sans_limite_lits: Optional[int]     # patients opérés si les lits étaient illimités
    capacite_sans_limite_places: Optional[int]   # ... si les places ambulatoires étaient illimitées
    ressource_limitante: str
    erreurs_coherence: int
    temps_s: float
    courbe: list[tuple[int, float]] = field(default_factory=list)   # (patients inscrits, occupation % vacation)
    par_semaine: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------------- patients
def _sejours_reels():
    df = ml.PREP.charger_et_preparer(chemins.CSV_HISTORIQUE)
    return df[["duree_bloc_heures", "type_capacite", "duree_avant_operation", "duree_apres_operation"]].to_dict("records")


def _poids_chirurgiens(lundi: date, semaines: int) -> dict[str, float]:
    minutes: Counter = Counter()
    for k in range(semaines):
        _, vacs, _ = P.V28.construire_semaine(lundi + timedelta(weeks=k))
        for v in vacs.values():
            if v.chirurgien_id not in (P.V28.ID_URGENCE, P.V28.ID_LIBRE):
                minutes[P.V28.NOM_PAR_ID[v.chirurgien_id]] += v.duree_minutes
    return dict(minutes)


def tirer_patients_profils_reels(n: int, lundi: date, semaines: int, graine: int = GRAINE_SATURATION
                                 ) -> list[SC.Patient]:
    """
    Générateur 2/3 — PROFILS DE SÉJOURS RÉELS, pour l'étude de saturation uniquement.

    N patients dont la durée au bloc, le mode (ambulatoire / hospitalisé) et les nuits avant / après sont ceux d'un
    séjour tiré au hasard dans machine_learning/donnees_hospitalieres.csv (OBSERVÉS ; durée arrondie à 5 min,
    au moins 15 min ; nuits avant plafonnées à 3, nuits après entre 1 et 30 pour un hospitalisé). HYPOTHÈSES :
    chirurgien tiré au prorata de son temps de vacation sur l'horizon (la demande a la forme de l'offre),
    priorité 2 pour tous, date au plus tôt = premier lundi. Graine : `graine` (GRAINE_SATURATION, --graine).
    Les séjours sont lus en mémoire ; aucun enregistrement individuel n'est écrit sur disque.
    """
    rng = random.Random(graine)
    sejours = _sejours_reels()
    poids = _poids_chirurgiens(lundi, semaines)
    noms, w = list(poids), list(poids.values())
    patients = []
    for k in range(n):
        s, chir = rng.choice(sejours), rng.choices(noms, w)[0]
        amb = s["type_capacite"] == "ambulatoire"
        patients.append(SC.Patient(
            id=S.pid_consultation(50_000 + k), chirurgien_id=S.id_chirurgien(chir),
            duree_bloc=max(15, int(round(s["duree_bloc_heures"] * 60 / 5)) * 5), ambulatoire=amb,
            nuits_pre_op=0 if amb else int(min(s["duree_avant_operation"], 3)),
            nuits_post_op=0 if amb else int(max(1, min(s["duree_apres_operation"], 30))),
            priorite=2, date_min=lundi, nom=f"SAT-{k + 1:04d}", specialite=SMA.specialite_de(chir)))
    return patients


# ---------------------------------------------------------------------------------------------------- étude
def programme_vide(lundi: date, semaines: int, hebergement: SC.ParametresHebergement) -> P.Programme:
    i1, i2 = SMA.construire_instances_v28(lundi, semaines, patients={}, hebergement=hebergement)
    return P.Programme(lundi, semaines, "vide", 0.0, 0, i1, i2, SC.SolutionPatients({}))


def etudier(semaines: int = 4, n_patients: Optional[int] = None, *, lundi: date = LUNDI_DEFAUT,
            hebergement: SC.ParametresHebergement = SC.HEBERGEMENT_SITE, confrere: bool = False,
            graine: int = GRAINE_SATURATION,
            pas_courbe: int = 10, analyser_ressources: bool = True) -> Resultat:
    """`analyser_ressources` : rejoue l'étude avec des lits puis des places illimités ; la ressource dont la levée
    augmente le plus la capacité est la ressource limitante (aucune : c'est le temps opératoire)."""
    t0 = chrono.perf_counter()
    prog = programme_vide(lundi, semaines, hebergement)
    fin = lundi + timedelta(weeks=semaines)
    fenetres = [v for v in prog.instance2.vacations.values() if v.jour < fin and not v.supplementaire]
    minutes_vacation = sum(v.duree_minutes for v in fenetres)
    minutes_utiles = sum(v.capacite_utile_minutes for v in fenetres)
    if n_patients is None:                  # assez pour déborder nettement : 1,6 x la capacité au temps moyen réel
        n_patients = int(1.6 * minutes_utiles / 77) + 20
    patients = tirer_patients_profils_reels(n_patients, lundi, semaines, graine)

    debut = datetime.combine(lundi, datetime.min.time())
    evts = [{"id": k, "heure": debut + timedelta(seconds=k), "type": "inscription", "auteur": "saturation",
             "patient_id": None,
             "contenu": {"patient": S.patient_vers_dict(p), "jour_min": lundi.isoformat(),
                         "chirurgiens": S.chirurgiens_possibles(p, confrere), "salle_id": None, "fenetre_id": None}}
            for k, p in enumerate(patients)]
    sim = S.simuler(prog, evts, debut + timedelta(seconds=n_patients + 60))

    places = {p.id: sim.intervention(p.id) for p in patients}
    dans = [p for p in patients if places[p.id] is not None and places[p.id].debut.date() < fin]
    debordes = [p for p in patients if places[p.id] is None or places[p.id].debut.date() >= fin]
    rang_debord = next((k + 1 for k, p in enumerate(patients) if places[p.id] is None
                        or places[p.id].debut.date() >= fin), None)

    courbe, cumul = [], 0.0
    for k, p in enumerate(patients, start=1):
        it = places[p.id]
        if it is not None and it.debut.date() < fin:
            cumul += p.duree_bloc
        if k % pas_courbe == 0 or k == n_patients:
            courbe.append((k, 100 * cumul / minutes_vacation))

    lits, plcs = sim.modele.hebergement.occupation_par_jour()             # places : pic de la journée
    jours = sorted({v.jour for v in fenetres})
    h = hebergement
    pic_lits, pic_places = max((lits.get(j, 0) for j in jours), default=0), max((plcs.get(j, 0) for j in jours), default=0)
    jours_lits_pleins = sum(lits.get(j, 0) >= h.cap_lits for j in jours)
    jours_places_pleines = sum(plcs.get(j, 0) >= h.cap_places for j in jours)
    occ_utile = 100 * sum(p.duree_bloc for p in dans) / minutes_utiles
    part_hosp = 100 * sum(not p.ambulatoire for p in debordes) / len(debordes) if debordes else 0.0
    seuils, cumul = {50: None, 80: None, 90: None}, 0.0
    for k, p in enumerate(patients, start=1):
        if places[p.id] is not None and places[p.id].debut.date() < fin:
            cumul += p.duree_bloc
        for pct in seuils:
            if seuils[pct] is None and cumul >= pct / 100 * minutes_utiles:
                seuils[pct] = k

    sans_lits = sans_places = None
    limitante = "bloc (temps opératoire)"
    if analyser_ressources:
        illimite = 10_000
        options = dict(semaines=semaines, n_patients=n_patients, lundi=lundi, confrere=confrere, graine=graine,
                       analyser_ressources=False)
        sans_lits = etudier(hebergement=SC.ParametresHebergement(illimite, h.cap_places, 0), **options).places_dans_horizon
        sans_places = etudier(hebergement=SC.ParametresHebergement(h.lits_disponibles_par_jour, illimite, h.reserve_lits),
                              **options).places_dans_horizon
        gains = {"lits d'hospitalisation": sans_lits - len(dans), "places ambulatoires": sans_places - len(dans)}
        cle, gain = max(gains.items(), key=lambda kv: kv[1])
        if gain > 0.03 * len(dans):                         # au moins 3 % de patients en plus si on lève la contrainte
            limitante = cle

    par_semaine = []
    for k in range(semaines):
        l0 = lundi + timedelta(weeks=k)
        vk = [v for v in fenetres if l0 <= v.jour < l0 + timedelta(weeks=1)]
        pk = [p for p in dans if l0 <= places[p.id].debut.date() < l0 + timedelta(weeks=1)]
        par_semaine.append({"semaine": l0, "type": SC.type_semaine(l0), "patients": len(pk),
                            "occupation_pct": 100 * sum(p.duree_bloc for p in pk) / max(1, sum(v.duree_minutes for v in vk)),
                            "pic_lits": max((lits.get(l0 + timedelta(days=d), 0) for d in range(5)), default=0)})

    return Resultat(semaines, hebergement, n_patients, minutes_vacation, minutes_utiles, len(dans), rang_debord,
                    len(sim.en_attente()), 100 * sum(p.duree_bloc for p in dans) / minutes_vacation, occ_utile,
                    pic_lits, jours_lits_pleins, pic_places, jours_places_pleines, part_hosp, seuils,
                    sans_lits, sans_places, limitante,
                    len(sim.modele.verifier_coherence()), chrono.perf_counter() - t0, courbe, par_semaine)


# ---------------------------------------------------------------------------------------------------- rapport
def rapport(r: Resultat) -> str:
    h = r.hebergement
    lignes = [
        f"# Saturation du bloc — {r.semaines} semaine(s) à partir du {LUNDI_DEFAUT:%d/%m/%Y}",
        "",
        f"Capacités : {h.lits_disponibles_par_jour} lits (dont {h.reserve_lits} de réserve, {h.cap_lits} programmables), "
        f"{h.cap_places} places ambulatoires. Temps de vacation : {r.minutes_vacation / 60:.0f} h "
        f"(capacité utile {r.minutes_utiles / 60:.0f} h, marge de 10 % pour les aléas).",
        "",
        "| Indicateur | Valeur |", "|---|---|",
        f"| **Patients opérés dans l'horizon (capacité)** | **{r.places_dans_horizon}** "
        f"({r.places_dans_horizon / r.semaines:.0f} par semaine) |",
        *(f"| Patients inscrits pour remplir {pct} % de la capacité utile | {k or 'non atteint'} |"
          for pct, k in r.seuils.items()),
        f"| Premier patient sans place dans l'horizon (son chirurgien est complet) | n° {r.premier_debordement or '—'} |",
        f"| Occupation du temps de vacation | {r.occupation_finale_pct:.1f} % |",
        f"| Occupation de la capacité utile | {r.occupation_utile_pct:.1f} % |",
        f"| Pic de lits occupés | {r.pic_lits} / {h.cap_lits} ({r.jours_lits_pleins} jour(s) plein(s)) |",
        f"| Pic de places ambulatoires | {r.pic_places} / {h.cap_places} ({r.jours_places_pleines} jour(s) plein(s)) |",
        f"| Hospitalisés parmi les patients débordés | {r.debordes_hospitalises_pct:.0f} % |",
        *([f"| Capacité si les lits étaient illimités | {r.capacite_sans_limite_lits} patients |",
           f"| Capacité si les places ambulatoires étaient illimitées | {r.capacite_sans_limite_places} patients |"]
          if r.capacite_sans_limite_lits is not None else []),
        f"| **Ressource limitante** | **{r.ressource_limitante}** |",
        f"| Liste d'attente / erreurs de cohérence | {r.en_attente} / {r.erreurs_coherence} |",
        f"| Patients injectés / temps de calcul | {r.n_patients} / {r.temps_s:.0f} s |",
        "", "## Par semaine", "", "| Semaine | Type | Patients | Occupation | Pic de lits |", "|---|---|---|---|---|",
        *(f"| {s['semaine']:%d/%m} | {s['type']} | {s['patients']} | {s['occupation_pct']:.0f} % | {s['pic_lits']} |"
          for s in r.par_semaine),
        "", "## Occupation en fonction du nombre de patients inscrits", "",
        "| Patients | Occupation du temps de vacation |", "|---|---|",
        *(f"| {k} | {o:.0f} % |" for k, o in r.courbe[::max(1, len(r.courbe) // 15)]),
    ]
    return "\n".join(lignes) + "\n"


def main(argv=None) -> Resultat:
    ap = argparse.ArgumentParser(description="Étude de saturation du bloc opératoire")
    ap.add_argument("--semaines", type=int, default=4)
    ap.add_argument("--patients", type=int, default=None, help="par défaut : assez pour déborder (1,6 x la capacité)")
    ap.add_argument("--lits", type=int, default=SC.HEBERGEMENT_SITE.lits_disponibles_par_jour)
    ap.add_argument("--reserve", type=int, default=SC.HEBERGEMENT_SITE.reserve_lits)
    ap.add_argument("--places", type=int, default=SC.HEBERGEMENT_SITE.places_ambulatoires_par_jour)
    ap.add_argument("--confrere", action="store_true", help="les patients acceptent un confrère du service")
    ap.add_argument("--graine", type=int, default=GRAINE_SATURATION)
    a = ap.parse_args(argv)
    r = etudier(a.semaines, a.patients, confrere=a.confrere, graine=a.graine,
                hebergement=SC.ParametresHebergement(a.lits, a.places, a.reserve))
    texte = rapport(r)
    print(texte)
    DOSSIER_RESULTATS.mkdir(exist_ok=True)
    (DOSSIER_RESULTATS / "saturation.md").write_text(texte, encoding="utf-8")
    with open(DOSSIER_RESULTATS / "saturation_courbe.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("patients_inscrits", "occupation_vacation_pct"), *r.courbe])
    print(f"Rapport : {DOSSIER_RESULTATS / 'saturation.md'}")
    return r


if __name__ == "__main__":
    main()
