# -*- coding: utf-8 -*-
"""
sorties.py  (v2)
================

Format de SORTIE unique des métaheuristiques (RS, Tabou, AGS), niveaux 1 et 2.

Depuis la v2, les trois algorithmes minimisent la MÊME fonction objectif à
chaque niveau (voir structures_communes.py) : `score_final` est donc
directement comparable d'un algorithme à l'autre. Les INDICATEURS
(taux d'occupation, dépassements, pics, patients non placés...) complètent
le score pour expliquer d'où il vient et servir aux agents.

Contenu
-------
    1. IndicateursNiveau1 / IndicateursNiveau2
    2. PointConvergence / SuiviExecution          (chrono, compteurs, convergence)
    3. ResultatMetaheuristique                    (LE format de sortie)
    4. Fabriques : resultat_niveau1(), resultat_niveau2()
    5. Sérialisation JSON
    6. Comparaison : comparer_resultats(), afficher_comparaison(), courbes_convergence()
    7. Affichages communs : afficher_planning(), afficher_affectation_patients()

Utilisation type
----------------
    suivi = SuiviExecution()
    with suivi:
        ...
        suivi.enregistrer(iteration, score_courant, meilleur_score)
    res = resultat_niveau1("TABOU", instance, solution, score_initial=s0, suivi=suivi, parametres=params)
    res.sauvegarder("resultats/TABOU_n1.json")
"""
from __future__ import annotations

import json
import sys
import time as _chrono
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Optional, Union

# structures_communes.py partagé par tout le dépôt : dossier commun/
_COMMUN = str(Path(__file__).resolve().parents[1] / "commun")
if _COMMUN not in sys.path:
    sys.path.insert(0, _COMMUN)

from structures_communes import (  # noqa: E402
    JOURS_FR, EvaluationNiveau2, InstanceNiveau2, InstanceProbleme, NomAlgo,
    SolutionPatients, SolutionPlanning, Vacation, calculer_occupation_par_jour, construire_vacations,
    evaluer_niveau2, evaluer_planning, penalite_priorite_patient, verifier_solution_niveau1,
)

from validation import valider_niveau1, valider_niveau2  # noqa: E402  (commun/validation.py)

VERSION_FORMAT = "2.0"


# =============================================================================
# 1. INDICATEURS
# =============================================================================

@dataclass
class IndicateursNiveau1:
    faisable: bool                       # aucune violation de contrainte forte
    nb_erreurs_contraintes: int
    conflits_salles: int
    conflits_chirurgiens: int
    salles_differentes: int
    fragmentation: int
    nb_blocs_total: int
    nb_blocs_places: int
    nb_vacations: int
    heures_demandees: float
    heures_planifiees: float
    heures_par_chirurgien: dict[int, float] = field(default_factory=dict)
    vacations_par_chirurgien: dict[int, int] = field(default_factory=dict)
    erreurs: list[str] = field(default_factory=list)


@dataclass
class IndicateursNiveau2:
    faisable: bool                       # tous placés, aucun dépassement de capacité
    nb_patients: int
    nb_places: int
    nb_non_places: int
    # --- bloc (vacations régulières) ---
    capacite_bloc_minutes: float
    charge_bloc_minutes: float
    taux_occupation_bloc_pct: float
    temps_inoccupe_minutes: float
    depassement_bloc_minutes: float
    nb_vacations_en_depassement: int
    nb_vacations_vides: int
    # --- vacations supplémentaires ---
    nb_vacations_supp_utilisees: int
    patients_en_supp: int
    # --- hébergement ---
    capacite_lits: int
    capacite_places: int
    pic_lits: int
    pic_places: int
    depassement_lits: int
    depassement_places: int
    variance_lits: float
    variance_places: float
    taux_occupation_lits_pct: float
    taux_occupation_places_pct: float
    occupation_lits_par_jour: dict[date, int] = field(default_factory=dict)
    occupation_places_par_jour: dict[date, int] = field(default_factory=dict)
    # --- priorité clinique (information, hors fonction objectif) ---
    retard_moyen_pondere_priorite: float = 0.0   # 0 = chacun au plus tôt possible, 1 = au plus tard
    non_places_par_priorite: dict[int, int] = field(default_factory=dict)


def calculer_indicateurs_niveau1(instance: InstanceProbleme, solution: SolutionPlanning) -> IndicateursNiveau1:
    ev = evaluer_planning(instance, solution)
    erreurs = verifier_solution_niveau1(instance, solution)
    vacations = construire_vacations(instance, solution)
    heures: dict[int, float] = {}
    nb_vac: dict[int, int] = {}
    for v in vacations.values():
        heures[v.chirurgien_id] = heures.get(v.chirurgien_id, 0.0) + v.duree_minutes / 60
        nb_vac[v.chirurgien_id] = nb_vac.get(v.chirurgien_id, 0) + 1
    return IndicateursNiveau1(
        faisable=not erreurs, nb_erreurs_contraintes=len(erreurs),
        conflits_salles=ev.conflits_salles, conflits_chirurgiens=ev.conflits_chirurgiens,
        salles_differentes=ev.salles_differentes, fragmentation=ev.fragmentation,
        nb_blocs_total=len(instance.blocs_a_placer), nb_blocs_places=len(solution.affectations),
        nb_vacations=len(vacations),
        heures_demandees=sum(c.besoin_heures_semaine for c in instance.chirurgiens.values()),
        heures_planifiees=sum(heures.values()),
        heures_par_chirurgien=heures, vacations_par_chirurgien=nb_vac, erreurs=erreurs,
    )


def calculer_indicateurs_niveau2(instance2: InstanceNiveau2, solution: SolutionPatients) -> IndicateursNiveau2:
    V = instance2.vacations
    ev = evaluer_niveau2(instance2, solution)
    charge = {vid: 0.0 for vid in V}
    for pid, vid in solution.affectations.items():
        if vid is not None:
            charge[vid] += instance2.patients[pid].duree_bloc
    reg = [vid for vid, v in V.items() if not v.supplementaire]
    lits, places = calculer_occupation_par_jour(instance2, solution)

    pen = [penalite_priorite_patient(instance2.patients[pid], vid, V)
           for pid, vid in solution.affectations.items() if vid is not None]
    np_prio: dict[int, int] = {}
    for pid in solution.non_places():
        pr = instance2.patients[pid].priorite
        np_prio[pr] = np_prio.get(pr, 0) + 1

    h = instance2.hebergement
    return IndicateursNiveau2(
        faisable=(ev.patients_non_places == 0 and ev.depassement_bloc_minutes == 0
                  and ev.depassement_lits == 0 and ev.depassement_places == 0),
        nb_patients=len(instance2.patients), nb_places=len(instance2.patients) - ev.patients_non_places,
        nb_non_places=ev.patients_non_places,
        capacite_bloc_minutes=sum(V[v].capacite_utile_minutes for v in reg),
        charge_bloc_minutes=sum(charge.values()),
        taux_occupation_bloc_pct=ev.taux_occupation_bloc_pct,
        temps_inoccupe_minutes=ev.temps_bloc_inoccupe_minutes,
        depassement_bloc_minutes=ev.depassement_bloc_minutes,
        nb_vacations_en_depassement=sum(charge[v] > V[v].capacite_utile_minutes + 1e-9 for v in V),
        nb_vacations_vides=sum(charge[v] == 0 for v in reg),
        nb_vacations_supp_utilisees=ev.nb_vacations_supp_utilisees, patients_en_supp=ev.patients_en_supp,
        capacite_lits=h.cap_lits, capacite_places=h.cap_places,
        pic_lits=ev.pic_lits, pic_places=ev.pic_places,
        depassement_lits=ev.depassement_lits, depassement_places=ev.depassement_places,
        variance_lits=ev.variance_occupation_lits, variance_places=ev.variance_occupation_places,
        taux_occupation_lits_pct=ev.taux_occupation_lits_pct, taux_occupation_places_pct=ev.taux_occupation_places_pct,
        occupation_lits_par_jour=dict(sorted(lits.items())), occupation_places_par_jour=dict(sorted(places.items())),
        retard_moyen_pondere_priorite=sum(pen) / len(pen) if pen else 0.0,
        non_places_par_priorite=dict(sorted(np_prio.items())),
    )


# =============================================================================
# 2. SUIVI D'EXÉCUTION
# =============================================================================

@dataclass
class PointConvergence:
    iteration: int          # itération (Tabou), évaluation (RS) ou génération (AGS)
    temps_s: float
    score_courant: float
    meilleur_score: float


class SuiviExecution:
    """
    Chronomètre + compteurs + courbe de convergence, identiques pour les 3 algorithmes.

        suivi = SuiviExecution(pas_enregistrement=10)
        with suivi:
            ...
            suivi.compter_evaluation()           # ou evaluer = suivi.compter(evaluer)
            suivi.enregistrer(it, score, meilleur)
    """

    def __init__(self, pas_enregistrement: int = 1):
        self.pas = max(1, pas_enregistrement)
        self.historique: list[PointConvergence] = []
        self.nb_iterations = 0
        self.nb_evaluations = 0
        self.nb_ameliorations = 0
        self.compteurs: dict[str, int] = {}
        self._t0: Optional[float] = None
        self.temps_s = 0.0

    def __enter__(self):
        self._t0 = _chrono.perf_counter()
        return self

    def __exit__(self, *exc):
        self.temps_s = self.ecoule()
        return False

    def ecoule(self) -> float:
        return 0.0 if self._t0 is None else _chrono.perf_counter() - self._t0

    def compter(self, fonction: Callable) -> Callable:
        def enveloppe(*a, **k):
            self.nb_evaluations += 1
            return fonction(*a, **k)
        return enveloppe

    def compter_evaluation(self, n: int = 1):
        self.nb_evaluations += n

    def incrementer(self, nom: str, n: int = 1):
        self.compteurs[nom] = self.compteurs.get(nom, 0) + n

    def enregistrer(self, iteration: int, score_courant: float, meilleur_score: float):
        self.nb_iterations = max(self.nb_iterations, iteration)
        precedent = self.historique[-1].meilleur_score if self.historique else float("inf")
        ameliore = meilleur_score < precedent
        self.nb_ameliorations += ameliore
        if ameliore or iteration % self.pas == 0:
            self.historique.append(PointConvergence(iteration, self.ecoule(), score_courant, meilleur_score))


# =============================================================================
# 3. FORMAT DE SORTIE
# =============================================================================

@dataclass
class ResultatMetaheuristique:
    """Sortie standard d'une exécution de métaheuristique."""
    # --- identification ---
    algo: NomAlgo
    niveau: int
    nom_instance: str
    variante: str = ""                                # ex. "avec vacations supp."
    # --- score (fonction objectif commune du niveau) ---
    score_initial: float = 0.0
    score_final: float = 0.0
    detail_score: dict[str, float] = field(default_factory=dict)   # N2 : + "report" (pénalité de report)
    score_recherche: Optional[float] = None    # score optimisé par l'algorithme (N2 : score commun + report)
    # --- faisabilité (validateur indépendant commun/validation.py, D9) ---
    validation: dict[str, Any] = field(default_factory=dict)        # {"faisable", "par_type", "violations"}
    # --- indicateurs ---
    indicateurs: Union[IndicateursNiveau1, IndicateursNiveau2, None] = None
    # --- solution ---
    solution: dict[int, Optional[int]] = field(default_factory=dict)   # N1 : bloc->plage ; N2 : patient->vacation
    vacations: dict[int, Vacation] = field(default_factory=dict)       # N1 : produites ; N2 : utilisables
    # --- exécution ---
    parametres: dict[str, Any] = field(default_factory=dict)
    graine: Optional[int] = None
    temps_calcul_s: float = 0.0
    nb_iterations: int = 0
    nb_evaluations: int = 0
    compteurs: dict[str, int] = field(default_factory=dict)
    historique: list[PointConvergence] = field(default_factory=list)
    # --- méta ---
    horodatage: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    version_format: str = VERSION_FORMAT
    notes: str = ""

    @property
    def nom(self) -> str:
        return f"{self.algo}" + (f" ({self.variante})" if self.variante else "")

    @property
    def faisable(self) -> bool:
        """Verdict du validateur indépendant (à défaut, ancien indicateur pour les JSON antérieurs)."""
        if self.validation:
            return bool(self.validation.get("faisable"))
        return bool(self.indicateurs and self.indicateurs.faisable)

    @property
    def gain_pct(self) -> float:
        return 100 * (self.score_initial - self.score_final) / self.score_initial if self.score_initial else 0.0

    def solution_planning(self) -> SolutionPlanning:
        return SolutionPlanning(dict(self.solution))

    def solution_patients(self) -> SolutionPatients:
        return SolutionPatients(dict(self.solution))

    def resume(self) -> dict[str, Any]:
        """Une ligne de tableau comparatif."""
        ligne = {
            "algo": self.nom, "niveau": self.niveau, "instance": self.nom_instance,
            "score_initial": round(self.score_initial, 1), "score_final": round(self.score_final, 1),
            "score_recherche": None if self.score_recherche is None else round(self.score_recherche, 1),
            "gain_pct": round(self.gain_pct, 1), "faisable": self.faisable,
            "temps_s": round(self.temps_calcul_s, 2), "iterations": self.nb_iterations,
            "evaluations": self.nb_evaluations,
        }
        ind = self.indicateurs
        if isinstance(ind, IndicateursNiveau1):
            ligne.update(conflits=ind.conflits_salles + ind.conflits_chirurgiens,
                         salles_diff=ind.salles_differentes, fragmentation=ind.fragmentation,
                         nb_vacations=ind.nb_vacations)
        elif isinstance(ind, IndicateursNiveau2):
            d = self.detail_score
            ligne.update(score_blocs=round(d.get("score_blocs", 0)), score_lits=round(d.get("score_lits", 0)),
                         score_places=round(d.get("score_places", 0)),
                         non_places=ind.nb_non_places, occ_bloc_pct=round(ind.taux_occupation_bloc_pct, 1),
                         inoccupe_min=round(ind.temps_inoccupe_minutes),
                         depass_bloc_min=round(ind.depassement_bloc_minutes),
                         pic_lits=ind.pic_lits, depass_lits=ind.depassement_lits,
                         pic_places=ind.pic_places, depass_places=ind.depassement_places,
                         vac_supp=ind.nb_vacations_supp_utilisees)
        return ligne

    # ---------- sérialisation ----------
    def to_dict(self) -> dict[str, Any]:
        return _vers_json(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def sauvegarder(self, chemin: Union[str, Path]) -> Path:
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(self.to_json(), encoding="utf-8")
        return chemin

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResultatMetaheuristique":
        d = dict(d)
        if d.get("indicateurs") is not None:
            ind = dict(d["indicateurs"])
            if d["niveau"] == 1:
                for cle in ("heures_par_chirurgien", "vacations_par_chirurgien"):
                    ind[cle] = {int(k): v for k, v in ind.get(cle, {}).items()}
                d["indicateurs"] = IndicateursNiveau1(**ind)
            else:
                for cle in ("occupation_lits_par_jour", "occupation_places_par_jour"):
                    ind[cle] = {date.fromisoformat(k): v for k, v in ind.get(cle, {}).items()}
                ind["non_places_par_priorite"] = {int(k): v for k, v in ind.get("non_places_par_priorite", {}).items()}
                d["indicateurs"] = IndicateursNiveau2(**ind)
        d["solution"] = {int(k): v for k, v in d.get("solution", {}).items()}
        d["vacations"] = {int(k): _vacation_depuis_dict(v) for k, v in d.get("vacations", {}).items()}
        d["historique"] = [PointConvergence(**p) for p in d.get("historique", [])]
        noms = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in noms})

    @classmethod
    def charger(cls, chemin: Union[str, Path]) -> "ResultatMetaheuristique":
        return cls.from_dict(json.loads(Path(chemin).read_text(encoding="utf-8")))


# =============================================================================
# 4. FABRIQUES
# =============================================================================

def _detail(evaluation) -> dict[str, float]:
    if evaluation is None:
        return {}
    return {k: v for k, v in asdict(evaluation).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def resultat_niveau1(algo: NomAlgo, instance: InstanceProbleme, solution: SolutionPlanning, *,
                     score_initial: float, suivi: Optional[SuiviExecution] = None, parametres: Any = None,
                     graine: Optional[int] = None, variante: str = "", notes: str = "") -> ResultatMetaheuristique:
    """Sortie N1 : le score final est recalculé avec la fonction objectif commune."""
    ev = evaluer_planning(instance, solution)
    return ResultatMetaheuristique(
        algo=algo, niveau=1, nom_instance=instance.nom, variante=variante,
        score_initial=score_initial, score_final=ev.score_total, detail_score=_detail(ev),
        validation=valider_niveau1(instance, solution).to_dict(),
        indicateurs=calculer_indicateurs_niveau1(instance, solution),
        solution=dict(solution.affectations), vacations=construire_vacations(instance, solution),
        **_champs_execution(suivi, parametres, graine), notes=notes,
    )


def resultat_niveau2(algo: NomAlgo, instance2: InstanceNiveau2, solution: SolutionPatients, *,
                     score_initial: float, suivi: Optional[SuiviExecution] = None, parametres: Any = None,
                     graine: Optional[int] = None, variante: str = "", notes: str = "") -> ResultatMetaheuristique:
    """Sortie N2 : le score final est recalculé avec la fonction objectif commune (Tabou)."""
    ev = evaluer_niveau2(instance2, solution)
    utilisees = {v for v in solution.affectations.values() if v is not None}
    vacations = {vid: v for vid, v in instance2.vacations.items() if not v.supplementaire or vid in utilisees}
    return ResultatMetaheuristique(
        algo=algo, niveau=2, nom_instance=instance2.nom, variante=variante,
        score_initial=score_initial, score_final=ev.score_total, detail_score=_detail(ev),
        validation=valider_niveau2(instance2, solution).to_dict(),
        indicateurs=calculer_indicateurs_niveau2(instance2, solution),
        solution=dict(solution.affectations), vacations=vacations,
        **_champs_execution(suivi, parametres, graine), notes=notes,
    )


def _champs_execution(suivi, parametres, graine) -> dict[str, Any]:
    params = _vers_json(parametres) if parametres is not None else {}
    if not isinstance(params, dict):
        params = {"valeur": params}
    if graine is None:
        graine = params.get("graine")
    if suivi is None:
        return dict(parametres=params, graine=graine)
    return dict(parametres=params, graine=graine, temps_calcul_s=suivi.temps_s or suivi.ecoule(),
                nb_iterations=suivi.nb_iterations, nb_evaluations=suivi.nb_evaluations,
                compteurs=dict(suivi.compteurs), historique=list(suivi.historique))


# =============================================================================
# 5. SÉRIALISATION
# =============================================================================

def _vers_json(obj: Any) -> Any:
    """Conversion récursive vers des types JSON (dates en ISO, clés en str)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _vers_json(getattr(obj, f.name)) for f in fields(obj) if f.name != "cache_domaines"}
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {(k.isoformat() if isinstance(k, (date, datetime)) else str(k)): _vers_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_vers_json(v) for v in obj]
    if isinstance(obj, float) and obj in (float("inf"), float("-inf")):
        return None
    return obj


def _vacation_depuis_dict(d: dict) -> Vacation:
    d = dict(d)
    d["jour"] = date.fromisoformat(d["jour"])
    d["heure_debut"] = time.fromisoformat(d["heure_debut"])
    d["heure_fin"] = time.fromisoformat(d["heure_fin"])
    d["creneaux_ids"] = tuple(d.get("creneaux_ids", ()))
    return Vacation(**d)


def sauvegarder_resultats(resultats: list[ResultatMetaheuristique], chemin: Union[str, Path]) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps([r.to_dict() for r in resultats], ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin


def charger_resultats(chemin: Union[str, Path]) -> list[ResultatMetaheuristique]:
    """Charge un fichier (un résultat ou une liste) ou TOUS les .json d'un dossier."""
    chemin = Path(chemin)
    fichiers = sorted(chemin.glob("*.json")) if chemin.is_dir() else [chemin]
    res = []
    for f in fichiers:
        contenu = json.loads(f.read_text(encoding="utf-8"))
        res += [ResultatMetaheuristique.from_dict(d) for d in (contenu if isinstance(contenu, list) else [contenu])]
    return res


def vacations_depuis_resultat(resultat: ResultatMetaheuristique) -> dict[int, Vacation]:
    """Passerelle N1 -> N2 via le format de sortie."""
    if resultat.niveau != 1:
        raise ValueError("Seul un résultat de niveau 1 produit des vacations d'entrée pour le niveau 2.")
    return dict(resultat.vacations)


# =============================================================================
# 6. COMPARAISON
# =============================================================================

def comparer_resultats(resultats: list[ResultatMetaheuristique], en_dataframe: bool = True):
    """Tableau comparatif, une ligne par résultat (DataFrame pandas si disponible)."""
    if len({r.niveau for r in resultats}) > 1:
        raise ValueError("Ne comparer que des résultats d'un même niveau.")
    if len({r.nom_instance for r in resultats}) > 1:
        print("⚠ Instances différentes : les scores ne sont pas comparables entre elles.")
    lignes = [r.resume() for r in resultats]
    if en_dataframe:
        try:
            import pandas as pd
            return pd.DataFrame(lignes)
        except ImportError:
            pass
    return lignes


def afficher_comparaison(resultats: list[ResultatMetaheuristique]) -> None:
    lignes = comparer_resultats(resultats, en_dataframe=False)
    if not lignes:
        return
    cles = list(lignes[0])
    larg = {k: max(len(k), *(len(_fmt(l.get(k))) for l in lignes)) for k in cles}
    print(" | ".join(k.ljust(larg[k]) for k in cles))
    print("-+-".join("-" * larg[k] for k in cles))
    for l in lignes:
        print(" | ".join(_fmt(l.get(k)).ljust(larg[k]) for k in cles))


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.1f}" if abs(v) < 1e4 else f"{v:,.0f}"
    return str(v)


def courbes_convergence(resultats: list[ResultatMetaheuristique], echelle_log: bool = True, ax=None):
    """Meilleur score en fonction du temps pour chaque résultat (matplotlib)."""
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    for r in resultats:
        if r.historique:
            ax.step([p.temps_s for p in r.historique], [p.meilleur_score for p in r.historique],
                    where="post", label=f"{r.nom} (N{r.niveau})")
    ax.set_xlabel("Temps (s)")
    ax.set_ylabel("Meilleur score")
    if echelle_log:
        ax.set_yscale("symlog")
    ax.legend()
    ax.grid(alpha=0.3)
    return ax


# =============================================================================
# 7. AFFICHAGES COMMUNS
# =============================================================================

def barre(valeur: float, maximum: float, largeur: int = 20) -> str:
    """[█████░░░░░] ; un '!' final signale un dépassement."""
    if maximum <= 0:
        return "[" + "░" * largeur + "]"
    ratio = valeur / maximum
    plein = min(largeur, int(round(ratio * largeur)))
    return "[" + "█" * plein + "░" * (largeur - plein) + "]" + ("!" if ratio > 1.0 + 1e-9 else " ")


def afficher_planning(instance: InstanceProbleme, solution: SolutionPlanning, titre: str = "PLANNING NIVEAU 1"):
    """Grille jour x salle x créneau, vacations reconstituées, résumé par chirurgien et score."""
    plage_vers_chir = {pid: instance.chirurgiens[instance.blocs_a_placer[b].chirurgien_id].nom
                       for b, pid in solution.affectations.items()}
    plage_par_case = {(p.salle_id, p.creneau_id): p for p in instance.plages_bloc.values()}
    jours = sorted({c.jour for c in instance.creneaux.values()})
    creneaux_tries = sorted(instance.creneaux.values(), key=lambda c: (c.jour, c.heure_debut))
    salles = sorted(instance.salles.values(), key=lambda s: s.id)
    larg = max(12, max(len(s.nom) for s in salles) + 2)

    print("=" * 74 + f"\n  {titre}\n" + "=" * 74)
    for jour in jours:
        print(f"\n  {JOURS_FR[jour.weekday()]} {jour:%d/%m/%Y}\n  " + "─" * 70)
        print("  " + "Horaire".ljust(14) + "".join(s.nom.ljust(larg) for s in salles))
        for c in [c for c in creneaux_tries if c.jour == jour]:
            ligne = "  " + f"{c.heure_debut:%H:%M}-{c.heure_fin:%H:%M}".ljust(14)
            for s in salles:
                p = plage_par_case.get((s.id, c.id))
                contenu = ("-" if p is None else "[URGENCE]" if p.type_plage == "URGENCE"
                           else "[FERMÉ]" if p.type_plage == "INDISPONIBLE" else plage_vers_chir.get(p.id, "libre"))
                ligne += contenu.ljust(larg)
            print(ligne)

    vacations = construire_vacations(instance, solution)
    print("\n  VACATIONS RECONSTITUÉES\n  " + "─" * 70)
    for v in sorted(vacations.values(), key=lambda v: (v.jour, v.heure_debut, v.salle_id)):
        print(f"  {instance.chirurgiens[v.chirurgien_id].nom:8s} | {instance.salles[v.salle_id].nom:8s} | "
              f"{v.jour:%d/%m/%Y} | {v.heure_debut:%H:%M} - {v.heure_fin:%H:%M}")
    print("\n  RÉSUMÉ PAR CHIRURGIEN\n  " + "─" * 70)
    for cid, chir in instance.chirurgiens.items():
        vs = [v for v in vacations.values() if v.chirurgien_id == cid]
        print(f"  {chir.nom:8s} | {sum(v.duree_minutes for v in vs) / 60:4.0f} h | {len(vs)} vacation(s) "
              f"| salle(s) {sorted({v.salle_id for v in vs})}")
    ev = evaluer_planning(instance, solution)
    erreurs = verifier_solution_niveau1(instance, solution)
    print("\n  SCORE NIVEAU 1 (à minimiser)\n  " + "─" * 70)
    print(f"  Score total            : {ev.score_total:.0f}")
    print(f"  Conflits de salle      : {ev.conflits_salles}")
    print(f"  Conflits de chirurgien : {ev.conflits_chirurgiens}")
    print(f"  Salles différentes     : {ev.salles_differentes}  (x100 = {ev.salles_differentes * 100})")
    print(f"  Fragmentation          : {ev.fragmentation}  (x50 = {ev.fragmentation * 50})")
    print(f"  Contraintes fortes     : {'OK' if not erreurs else '; '.join(erreurs)}")
    print("=" * 74)


def afficher_scores_par_ressource(ev: EvaluationNiveau2, titre: str = "SCORES PAR RESSOURCE (coût à minimiser)"):
    total = ev.score_total or 1.0
    print("┌" + "─" * 86 + "┐")
    print(f"│ {titre:<84} │")
    print("├" + "─" * 86 + "┤")
    print(f"│ {'Ressource':<10}│{'Score':>10} │{'Part':>6} │{'Occ. moy.':>10} │{'Pic':>5} │{'Dépass.':>8} │{'Lissage(var)':>13} │")
    print("├" + "─" * 86 + "┤")
    lignes = [
        ("Blocs", ev.score_blocs, ev.taux_occupation_bloc_pct, "-", f"{ev.depassement_bloc_minutes:.0f}min", "-"),
        ("Lits", ev.score_lits, ev.taux_occupation_lits_pct, ev.pic_lits, str(ev.depassement_lits),
         f"{ev.variance_occupation_lits:.2f}"),
        ("Places", ev.score_places, ev.taux_occupation_places_pct, ev.pic_places, str(ev.depassement_places),
         f"{ev.variance_occupation_places:.2f}"),
    ]
    for nom, sc, occ, pic, dep, var in lignes:
        print(f"│ {nom:<10}│{sc:>10,.0f} │{sc / total * 100:>5.1f}% │{occ:>9.1f}% │{str(pic):>5} │{dep:>8} │{var:>13} │")
    print("├" + "─" * 86 + "┤")
    print(f"│ {'TOTAL':<10}│{ev.score_total:>10,.0f} │{100.0:>5.1f}% │{'':>10} │{'':>5} │{'':>8} │{'':>13} │")
    print("└" + "─" * 86 + "┘")
    if ev.patients_non_places:
        print(f"  ⚠ {ev.patients_non_places} patient(s) non placé(s)")
    if ev.nb_vacations_supp_utilisees:
        print(f"  ★ {ev.nb_vacations_supp_utilisees} vacation(s) supplémentaire(s) utilisée(s) : "
              f"{ev.patients_en_supp} patient(s), {ev.minutes_en_supp:.0f} min")


def afficher_affectation_patients(instance2: InstanceNiveau2, solution: SolutionPatients,
                                  titre: str = "AFFECTATION DES PATIENTS (NIVEAU 2)", detail_patients: bool = True):
    """Vacation par vacation (remplissage), patients non placés, lits/places jour par jour, scores."""
    print("=" * 86 + f"\n  {titre}\n" + "=" * 86)
    par_vac: dict[int, list[int]] = {}
    for pid, vid in solution.affectations.items():
        if vid is not None:
            par_vac.setdefault(vid, []).append(pid)
    jour_courant = None
    for v in sorted(instance2.vacations.values(), key=lambda v: (v.jour, v.heure_debut, v.salle_id)):
        if v.jour != jour_courant:
            jour_courant = v.jour
            print(f"\n  {JOURS_FR[v.jour.weekday()].upper()} {v.jour:%d/%m/%Y}\n  " + "─" * 82)
        nom = instance2.noms_chirurgiens.get(v.chirurgien_id, f"Chir. {v.chirurgien_id}")
        pids = sorted(par_vac.get(v.id, []), key=lambda p: -instance2.patients[p].duree_bloc)
        charge = sum(instance2.patients[p].duree_bloc for p in pids)
        cap = v.capacite_utile_minutes
        alerte = " ⚠ DÉPASSEMENT" if charge > cap + 1e-9 else ""
        if v.supplementaire:
            alerte += " ★ SUPPL." + (f" (semaine +{v.semaine_decalage})" if v.semaine_decalage else "")
        print(f"  Vac {v.id:2d} | Salle {v.salle_id} | {nom:6s} | {v.heure_debut:%H:%M}-{v.heure_fin:%H:%M} | "
              f"{barre(charge, cap, 16)} {charge:4.0f}/{cap:.0f} min ({(charge / cap * 100 if cap else 0):3.0f}%){alerte}")
        if detail_patients:
            for pid in pids:
                p = instance2.patients[pid]
                sejour = ("ambulatoire" if p.ambulatoire else
                          f"hospit. {p.nuits_pre_op + p.nuits_post_op} nuit(s) (veille: {'oui' if p.nuits_pre_op else 'non'})")
                print(f"        · P{p.id:03d} {p.nom:8s} | {p.duree_bloc:3d} min | prio {p.priorite} | {sejour}")

    non_places = solution.non_places()
    if non_places:
        print(f"\n  PATIENTS NON PLACÉS ({len(non_places)})\n  " + "─" * 82)
        for pid in non_places:
            p = instance2.patients[pid]
            print(f"   - P{p.id:03d} {p.nom:8s} | {instance2.noms_chirurgiens.get(p.chirurgien_id, p.chirurgien_id)} "
                  f"| {p.duree_bloc} min | prio {p.priorite} | {'ambulatoire' if p.ambulatoire else 'hospitalisé'}")

    lits, places = calculer_occupation_par_jour(instance2, solution)
    h = instance2.hebergement
    print("\n  OCCUPATION DES LITS ET PLACES AMBULATOIRES\n  " + "─" * 82)
    for jour in sorted(set(lits) | set(places)):
        l, pl = lits.get(jour, 0), places.get(jour, 0)
        print(f"  {JOURS_FR[jour.weekday()]:9s} {jour:%d/%m} | lits   {barre(l, h.cap_lits, 14)} {l:2d}/{h.cap_lits} "
              f"| places {barre(pl, h.cap_places, 14)} {pl:2d}/{h.cap_places}")
    print()
    afficher_scores_par_ressource(evaluer_niveau2(instance2, solution))
