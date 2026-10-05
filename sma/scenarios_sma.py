# -*- coding: utf-8 -*-
"""
sma/scenarios_sma.py — Scénarios de test du système multi-agent (sma_urgences.py)
==================================================================================

Tous les scénarios portent sur le planning réel v28, semaine du lundi 12/10/2026 (paire) puis 19/10 (impaire_2).
Chaque scénario repart du MÊME programme initial (solution du niveau 2).

En ligne de commande (depuis la racine du dépôt ou depuis sma/) :
    python sma/scenarios_sma.py --liste                        # liste des scénarios
    python sma/scenarios_sma.py fracture_panne                 # un scénario (récit + programme + bilan)
    python sma/scenarios_sma.py fracture_panne --messages      # + tous les messages FIPA-ACL échangés
    python sma/scenarios_sma.py fracture_panne --gantt sorties # + Gantt avant / après en PNG
    python sma/scenarios_sma.py --tous                         # tous les scénarios, tableau récapitulatif

Depuis Python / un notebook :
    from scenarios_sma import lancer, tester_tous, SCENARIOS
    modele = lancer("journee_chargee", solution=ma_solution_N2)   # solution des métaheuristiques (sinon glouton)
    tester_tous()

Ajouter un scénario : écrire une fonction qui renvoie la liste des événements, puis l'ajouter à SCENARIOS.
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sma_urgences import (  # noqa: E402
    ID_PAR_NOM, ArriveeUrgence, BlocOperatoire, FinPanne, PanneAscenseur, ProlongationPanne,
    construire_instances_v28, jour_txt, patient_urgent, solution_n2_par_defaut,
)

LUNDI = date(2026, 10, 12)


def h(jour: int, heure: int, minute: int = 0) -> datetime:
    """h(13, 9, 40) = mardi 13/10/2026 à 9 h 40."""
    return datetime(2026, 10, jour, heure, minute)


# Spécialité des praticiens (HYPOTHÈSE reprise du jeu de test, voir SPECIALITES_V28 dans sma_urgences.py)
ORTHO, MAIN, VASC, RACHIS = ("CT", "Orthopédie"), ("LZ", "Main"), ("HA", "Vasculaire"), ("JE", "Rachis")


def urgence(pid: int, quand: datetime, praticien: tuple[str, str], duree: int, gravite: str, *,
            ambulatoire: bool = False, nuits: int = 1, nom: str = "") -> ArriveeUrgence:
    """Arrivée d'un patient urgent vu par `praticien` = (code, spécialité)."""
    code, spe = praticien
    p = patient_urgent(pid, ID_PAR_NOM[code], duree, specialite=spe, ambulatoire=ambulatoire,
                       nuits_post_op=0 if ambulatoire else nuits, nom=nom)
    return ArriveeUrgence(quand, p, gravite=gravite)


@dataclass
class Scenario:
    titre: str
    description: str
    evenements: Callable[[], list]
    jours: list[date]                  # jours à afficher
    fin: datetime                      # la simulation tourne jusqu'à cette heure
    attendu: str                       # ce que le SMA doit montrer


# =====================================================================================================
# SCÉNARIOS DÉTERMINISTES
# =====================================================================================================

SCENARIOS: dict[str, Scenario] = {
    "insertion_simple": Scenario(
        "Insertion dans une plage URGENCE",
        "Mercredi 11 h : entorse grave de cheville (orthopédie, urgente, 45 min, ambulatoire).",
        lambda: [urgence(9001, h(14, 11), ORTHO, 45, "urgente", ambulatoire=True, nom="Entorse grave")],
        [date(2026, 10, 14)], h(14, 20),
        "opérée à 13 h 30 par le chirurgien d'urgence dans la plage URGENCE, sans toucher au programme."),

    "fracture_panne": Scenario(
        "Fracture puis panne du monte-lit",
        "Mardi 9 h 40 : fracture du radius (urgente, 60 min, 1 nuit). 10 h 15 : panne du monte-lit jusqu'à 13 h.",
        lambda: [urgence(9001, h(13, 9, 40), ORTHO, 60, "urgente", nom="Fracture avant-bras"),
                 PanneAscenseur(h(13, 10, 15), "ML1", h(13, 13))],
        [date(2026, 10, 13)], h(13, 20),
        "insérée à 12 h chez CT ; la panne l'empêche de monter -> ré-insérée à 13 h 30 chez MO (même délai)."),

    "gravite_vitale": Scenario(
        "Gravité vitale",
        "Mardi 9 h 40 : la même fracture, déclarée VITALE (incision avant 10 h 40).",
        lambda: [urgence(9001, h(13, 9, 40), ORTHO, 60, "vitale")],
        [date(2026, 10, 13)], h(13, 20),
        "opérée dès 10 h ; P12 décalé de 60 min (le coût d'attente vital l'emporte)."),

    "gravite_differable": Scenario(
        "Gravité différable",
        "Mardi 9 h 40 : la même fracture, déclarée DIFFÉRABLE (24 h).",
        lambda: [urgence(9001, h(13, 9, 40), ORTHO, 60, "differable")],
        [date(2026, 10, 13)], h(13, 20),
        "prend le temps libre de fin de matinée (12 h) sans décaler personne."),

    "urgences_simultanees": Scenario(
        "Trois urgences en 20 minutes",
        "Mercredi 11 h, 11 h 10, 11 h 20 : deux orthopédie (une hospitalisée) et une main.",
        lambda: [urgence(9001, h(14, 11), ORTHO, 45, "urgente", ambulatoire=True),
                 urgence(9002, h(14, 11, 10), ("MO", "Orthopédie"), 60, "urgente"),
                 urgence(9003, h(14, 11, 20), MAIN, 60, "urgente", ambulatoire=True)],
        [date(2026, 10, 14)], h(14, 20),
        "le chirurgien d'urgence ne peut pas être dans 2 salles : la 3e urgence va en salle 5 avec LZ rappelé d'astreinte."),

    "journee_chargee": Scenario(
        "Journée chargée",
        "Jeudi : vitale 8 h 20, urgente 9 h, panne 10 h 30 prolongée jusqu'à 14 h 30, urgente 14 h.",
        lambda: [urgence(9101, h(15, 8, 20), ORTHO, 90, "vitale", nuits=3, nom="Fracture col du fémur"),
                 urgence(9102, h(15, 9), MAIN, 60, "urgente", ambulatoire=True, nom="Plaie de tendon"),
                 PanneAscenseur(h(15, 10, 30), "ML1", h(15, 12)),
                 ProlongationPanne(h(15, 11, 45), "ML1", h(15, 14, 30)),
                 urgence(9103, h(15, 14), ORTHO, 75, "urgente", nuits=2, nom="Luxation d'épaule")],
        [date(2026, 10, 15)], h(16, 20),
        "vitale à 8 h 35 ; P80 déprogrammé -> liste d'attente ; luxation reportée au vendredi avec alerte."),

    "panne_matinale": Scenario(
        "Longue panne dès l'ouverture",
        "Lundi 7 h 30 : panne du monte-lit jusqu'à 11 h.",
        lambda: [PanneAscenseur(h(12, 7, 30), "ML1", h(12, 11))],
        [date(2026, 10, 12)], h(12, 20),
        "ambulatoires avancés, hospitalisés repoussés après 11 h 20, déprogrammations et replacement en chaîne."),

    "chirurgien_absent": Scenario(
        "Chirurgien compétent absent",
        "Vendredi : main 10 h (urgente), ischémie vasculaire 11 h (VITALE), hernie discale 15 h (différable).",
        lambda: [urgence(9301, h(16, 10), MAIN, 60, "urgente", ambulatoire=True, nom="Section de tendon"),
                 urgence(9302, h(16, 11), VASC, 90, "vitale", nuits=2, nom="Ischémie aiguë"),
                 urgence(9303, h(16, 15), RACHIS, 75, "differable", nuits=3, nom="Hernie discale")],
        [date(2026, 10, 16), date(2026, 10, 20)], h(23, 20),
        "main -> plage URGENCE ; vitale -> TRANSFERT ; hernie -> mardi 20/10 (JE en astreinte) avec alerte."),

    "rattrapage": Scenario(
        "Panne réparée plus tôt que prévu",
        "Mardi 8 h 30 : panne annoncée jusqu'à 15 h ; réparée à 10 h 30.",
        lambda: [PanneAscenseur(h(13, 8, 30), "ML1", h(13, 15)), FinPanne(h(13, 10, 30), "ML1")],
        [date(2026, 10, 13)], h(13, 20),
        "P12 repris par MO l'après-midi pendant la panne, puis ramené à 11 h chez CT à la réparation."),

    "panne_sans_effet": Scenario(
        "Panne sans patient hospitalisé à monter",
        "Mercredi 8 h 30 : panne du monte-lit jusqu'à 15 h, réparée à 10 h 30.",
        lambda: [PanneAscenseur(h(14, 8, 30), "ML1", h(14, 15)), FinPanne(h(14, 10, 30), "ML1")],
        [date(2026, 10, 14)], h(14, 20),
        "programme inchangé (que des ambulatoires à monter) ; seuls des opérés attendent en salle de réveil."),
}


# =====================================================================================================
# SCÉNARIOS ALÉATOIRES (charge normale / surcharge)
# Profil calibré sur l'historique 2019-2022 (diagnostics de traumatologie, proxy d'urgence)
# =====================================================================================================

POIDS_JOUR = [0.18, 0.11, 0.27, 0.165, 0.255]                                   # lundi..vendredi
TRANCHES_HEURE = [(8, 10, .14), (10, 12, .20), (12, 13.5, .19), (13.5, 15.5, .25), (15.5, 17.5, .12), (17.5, 19, .03)]
DUREES = [30, 45, 60, 75, 90, 120, 150]
POIDS_DUREES = [.12, .22, .20, .14, .13, .12, .07]                              # médiane ~66 min
PROBA_AMBU = 0.67
NUITS, POIDS_NUITS = [1, 2, 3, 4, 5], [.55, .17, .11, .09, .08]
GRAVITES_TIRAGE = [("vitale", .10), ("urgente", .20), ("differable", .70)]
SPECIALITES_TIRAGE = [(ORTHO, .45), (("MO", "Orthopédie"), .15), (MAIN, .25), (RACHIS, .10), (VASC, .05)]


def _poisson(rng: random.Random, lam: float) -> int:
    seuil, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= seuil:
            return k
        k += 1


def semaine_aleatoire(taux_par_jour: float = 1.0, graine: int = 1, pannes: int = 0) -> list:
    """Urgences d'une semaine ouvrée (lundi 12/10) : nombre ~ Poisson(taux x 5 x poids du jour), heure, durée,
    ambulatoire, nuits et gravité tirés selon le profil ci-dessus ; + `pannes` pannes du monte-lit de 1 à 3 h."""
    rng = random.Random(graine)
    evts, pid = [], 9500
    for j in range(5):
        for _ in range(_poisson(rng, taux_par_jour * 5 * POIDS_JOUR[j])):
            a, b, _ = rng.choices(TRANCHES_HEURE, weights=[t[2] for t in TRANCHES_HEURE])[0]
            m = int(rng.uniform(a * 60, b * 60))
            prat = rng.choices([s for s, _ in SPECIALITES_TIRAGE], weights=[w for _, w in SPECIALITES_TIRAGE])[0]
            amb = rng.random() < PROBA_AMBU
            evts.append(urgence(pid, h(12 + j, m // 60, m % 60), prat,
                                rng.choices(DUREES, weights=POIDS_DUREES)[0],
                                rng.choices([g for g, _ in GRAVITES_TIRAGE], weights=[w for _, w in GRAVITES_TIRAGE])[0],
                                ambulatoire=amb, nuits=rng.choices(NUITS, weights=POIDS_NUITS)[0]))
            pid += 1
    for _ in range(pannes):
        j, debut = rng.randrange(5), rng.randrange(8 * 60, 14 * 60, 15)
        evts.append(PanneAscenseur(h(12 + j, debut // 60, debut % 60), "ML1",
                                   h(12 + j, debut // 60, debut % 60) + timedelta(minutes=rng.choice([60, 120, 180]))))
    return sorted(evts, key=lambda e: e.heure)


SEMAINE = [LUNDI + timedelta(days=k) for k in range(5)]
SCENARIOS.update({
    "semaine_normale": Scenario(
        "Semaine en charge normale",
        "Urgences aléatoires : 1 par jour en moyenne, aucune panne (graine 1).",
        lambda: semaine_aleatoire(1.0, graine=1), SEMAINE, h(23, 20),
        "la plupart des urgences passent sans toucher au programme ; une vitale arrivée quand aucun chirurgien compétent n'est libre est transférée."),
    "semaine_surcharge": Scenario(
        "Semaine en surcharge",
        "Urgences aléatoires : 3 par jour en moyenne + 2 pannes du monte-lit (graine 1).",
        lambda: semaine_aleatoire(3.0, graine=1, pannes=2), SEMAINE, h(23, 20),
        "plus de décalages, déprogrammations, liste d'attente, et des alertes (délais dépassés, transferts)."),
})


# =====================================================================================================
# EXÉCUTION
# =====================================================================================================

_INSTANCES = None


def instances_par_defaut():
    """Planning v28 + patients sur 2 semaines, et solution N2 par défaut (glouton commun) — calculés une fois."""
    global _INSTANCES
    if _INSTANCES is None:
        i1, i2 = construire_instances_v28(LUNDI, nb_semaines=2)
        _INSTANCES = (i1, i2, solution_n2_par_defaut(i2))
    return _INSTANCES


def lancer(nom: str, solution=None, instances=None, verbeux: int = 1, gantt: Optional[str] = None,
           afficher: bool = True) -> BlocOperatoire:
    """Joue un scénario. `instances` = (instance1, instance2) et `solution` = SolutionPatients des
    métaheuristiques ; par défaut : planning v28 + glouton commun."""
    sc = SCENARIOS[nom]
    if instances is None:
        i1, i2, sol_def = instances_par_defaut()
        instances, solution = (i1, i2), solution or sol_def
    modele = BlocOperatoire.depuis_v28(LUNDI, instances=instances, solution=solution, verbeux=verbeux)
    if verbeux:
        print(f"\n{'#' * 96}\n# {nom} — {sc.titre}\n# {sc.description}\n# Attendu : {sc.attendu}\n{'#' * 96}")
    if gantt:
        for j in sc.jours:
            modele.tracer_gantt(j, Path(gantt) / f"{nom}_{j:%d%m}_avant.png", f"{sc.titre} — {jour_txt(j)} — avant")
    for evt in sc.evenements():
        modele.planifier(evt)
    modele.executer_jusqu_a(sc.fin)
    if afficher and verbeux:
        for j in sc.jours:
            modele.afficher_jour(j, f"{sc.titre.upper()} — APRÈS")
        modele.afficher_bilan()
    if gantt:
        for j in sc.jours:
            modele.tracer_gantt(j, Path(gantt) / f"{nom}_{j:%d%m}_apres.png", f"{sc.titre} — {jour_txt(j)} — après")
    return modele


def tester_tous(solution=None, instances=None) -> list[dict]:
    """Joue tous les scénarios sans affichage et imprime un tableau récapitulatif (+ contrôle de cohérence)."""
    lignes = []
    for nom in SCENARIOS:
        m = lancer(nom, solution=solution, instances=instances, verbeux=0)
        b = m.bilan()
        lignes.append({"scénario": nom, "urgences": b["urgences_inserees"] + b["urgences_refusees"],
                       "dans délai": b["urgences_dans_delai"], "transférées": b["urgences_refusees"],
                       "attente moy (min)": b["attente_moyenne_urgence_min"], "décalés": b["patients_decales"],
                       "reportés": b["patients_reportes_autre_jour"], "confrère": b["patients_repris_par_un_confrere"],
                       "attente": b["patients_en_liste_attente"], "alertes": len(b["alertes"]),
                       "messages": b["messages_echanges"], "cohérence": "OK" if not b["erreurs_de_coherence"] else "ERREUR"})
    cols = list(lignes[0])
    larg = {c: max(len(c), *(len(str(l[c])) for l in lignes)) for c in cols}
    print("  ".join(c.ljust(larg[c]) for c in cols))
    print("  ".join("-" * larg[c] for c in cols))
    for l in lignes:
        print("  ".join(str(l[c]).ljust(larg[c]) for c in cols))
    return lignes


def main():
    ap = argparse.ArgumentParser(description="Scénarios de test du SMA de gestion des urgences")
    ap.add_argument("scenarios", nargs="*", help="nom(s) de scénario (voir --liste)")
    ap.add_argument("--liste", action="store_true", help="liste les scénarios")
    ap.add_argument("--tous", action="store_true", help="joue tous les scénarios et affiche un récapitulatif")
    ap.add_argument("--messages", action="store_true", help="affiche chaque message échangé entre agents")
    ap.add_argument("--gantt", metavar="DOSSIER", help="enregistre les Gantt avant / après dans ce dossier")
    o = ap.parse_args()
    if o.liste or not (o.scenarios or o.tous):
        for nom, sc in SCENARIOS.items():
            print(f"  {nom:<22} {sc.titre} — {sc.description}")
        return
    if o.tous:
        tester_tous()
        return
    for nom in o.scenarios:
        if nom not in SCENARIOS:
            sys.exit(f"Scénario inconnu : {nom} (voir --liste)")
        lancer(nom, verbeux=2 if o.messages else 1, gantt=o.gantt)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
