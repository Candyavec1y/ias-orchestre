# -*- coding: utf-8 -*-
"""
algorithme_genetique.py
=======================

Implémentation de l'algorithme génétique simple (AGS) pour les deux niveaux du problème :

Niveau 1 :
    affectation des blocs chirurgiens aux plages opératoires.

Niveau 2 :
    affectation des patients aux vacations.

Les structures de données, fonctions objectif et solutions initiales
communes aux métaheuristiques sont définies dans structures_communes.py
(contrat ProblemeGenetique, paramètres ParametresAGS).

Les résultats utilisent le format commun défini dans sorties.py :
ils sont directement comparables à ceux du recuit simulé (recuit_simulé.py)
et de la recherche taboue (tabou_fonctionnel).

Principe (score MINIMISÉ) :
    population initiale -> à chaque génération :
        élitisme (les meilleurs individus passent tels quels),
        sélection par tournoi,
        croisement PAR CHIRURGIEN (avec la probabilité taux_croisement),
        mutation (avec la probabilité taux_mutation),
    jusqu'au nombre de générations prévu.
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

# structures_communes.py partagé par tout le dépôt : dossier commun/
_COMMUN = str(Path(__file__).resolve().parents[1] / "commun")
if _COMMUN not in sys.path:
    sys.path.insert(0, _COMMUN)

from structures_communes import (  # noqa: E402
    EtatNiveau2,
    Individu,
    InstanceNiveau2,
    InstanceProbleme,
    ParametresAGS,
    ProblemeGenetique,
    SolutionPatients,
    SolutionPlanning,
    construire_affectation_initiale,
    construire_meilleure_affectation_initiale,
    evaluer_niveau2,
    evaluer_planning,
    generer_solution_initiale_niveau1,
    plages_possibles_pour_chirurgien,
    vacations_compatibles,
)

from sorties import (  # noqa: E402
    ResultatMetaheuristique,
    SuiviExecution,
    resultat_niveau1,
    resultat_niveau2,
)


# =============================================================================
# 1. PARAMÈTRES DE L'AGS
# =============================================================================

# Niveau 1 :
# petite instance (une quinzaine de blocs) : une population moyenne suffit.
PARAMETRES_AGS_N1 = ParametresAGS(
    taille_population=40,
    generations=150,
    taux_croisement=0.8,
    taux_mutation=0.3,
    taille_tournoi=3,
    elites=2,
    graine=42,
)


# Niveau 2 :
# chaque évaluation est plus coûteuse (lits, places, priorités) :
# population plus petite, mais la meilleure solution initiale commune
# fait partie de la population de départ (l'AGS ne peut pas faire pire).
PARAMETRES_AGS_N2 = ParametresAGS(
    taille_population=30,
    generations=120,
    taux_croisement=0.8,
    taux_mutation=0.4,
    taille_tournoi=3,
    elites=2,
    graine=42,
)


# =============================================================================
# 2. ADAPTATION DU NIVEAU 1 À L'AGS
# =============================================================================

class ProblemeGenetiqueNiveau1(ProblemeGenetique):
    """
    Adaptateur entre le niveau 1 et le moteur génétique.

    Chromosome :
        une plage par bloc (blocs triés par identifiant).

    Croisement :
        par chirurgien : tous les blocs d'un même chirurgien sont hérités
        du même parent, ce qui conserve ses plannings partiels cohérents.

    Mutation :
        déplacement d'un bloc vers une autre plage compatible
        avec son chirurgien.

    Les éventuels conflits (salle, chirurgien) ne sont pas interdits :
    ils sont pénalisés par la fonction objectif commune du niveau 1.
    """

    niveau = 1

    def __init__(self, instance: InstanceProbleme):
        self.instance = instance
        self.blocs = sorted(instance.blocs_a_placer)
        self.domaines = [
            plages_possibles_pour_chirurgien(instance, instance.blocs_a_placer[b].chirurgien_id)
            for b in self.blocs
        ]
        self.indices_par_chirurgien: dict[int, list[int]] = defaultdict(list)
        for i, b in enumerate(self.blocs):
            self.indices_par_chirurgien[instance.blocs_a_placer[b].chirurgien_id].append(i)
        self._cache: dict[tuple, float] = {}

    # ---------------- codage / évaluation ----------------
    def vers_solution(self, individu: Individu) -> SolutionPlanning:
        return SolutionPlanning(dict(zip(self.blocs, individu)))

    def depuis_solution(self, solution: SolutionPlanning) -> Individu:
        return [solution.affectations[b] for b in self.blocs]

    def evaluer(self, solution: SolutionPlanning) -> float:
        """Fonction objectif commune du niveau 1."""
        return evaluer_planning(self.instance, solution).score_total

    def cout(self, individu: Individu) -> float:
        cle = tuple(individu)
        if cle not in self._cache:
            self._cache[cle] = self.evaluer(self.vers_solution(individu))
        return self._cache[cle]

    def solution_initiale(self, rng: random.Random) -> SolutionPlanning:
        """Solution initiale faisable commune au projet (backtracking)."""
        return generer_solution_initiale_niveau1(self.instance, rng)

    # ---------------- opérateurs génétiques ----------------
    def individu_aleatoire(self, rng: random.Random) -> Individu:
        """Solution faisable commune (graine aléatoire) puis quelques mutations : population diversifiée."""
        individu = self.depuis_solution(generer_solution_initiale_niveau1(self.instance, rng))
        for _ in range(rng.randint(0, 3)):
            individu = self.muter(individu, rng)
        return individu

    def croiser(self, parent1: Individu, parent2: Individu,
                rng: random.Random) -> tuple[Individu, Individu]:
        enfant1, enfant2 = list(parent1), list(parent2)
        for indices in self.indices_par_chirurgien.values():
            if rng.random() < 0.5:
                for i in indices:
                    enfant1[i], enfant2[i] = parent2[i], parent1[i]
        return enfant1, enfant2

    def muter(self, individu: Individu, rng: random.Random) -> Individu:
        nouveau = list(individu)
        i = rng.randrange(len(nouveau))
        candidats = [p for p in self.domaines[i] if p != nouveau[i]]
        if candidats:
            nouveau[i] = rng.choice(candidats)
        return nouveau


# =============================================================================
# 3. ADAPTATION DU NIVEAU 2 À L'AGS
# =============================================================================

class ProblemeGenetiqueNiveau2(ProblemeGenetique):
    """
    Adaptateur entre le niveau 2 et le moteur génétique.

    Chromosome :
        une vacation par patient (patients triés par identifiant) ;
        None signifie que le patient est non placé.

    Croisement :
        par chirurgien : les patients d'un chirurgien ne partagent les vacations
        qu'entre eux ; échanger tout le bloc d'un chirurgien garde des vacations cohérentes.

    Mutation :
        déplacement d'un patient vers une autre vacation compatible,
        ou échange avec un patient du même chirurgien.

    Les dépassements éventuels ne sont pas interdits :
    ils sont pénalisés par la fonction objectif commune du niveau 2.
    """

    niveau = 2

    def __init__(self, instance: InstanceNiveau2, solution_depart: SolutionPatients | None = None):
        self.instance = instance
        self.solution_depart = solution_depart.copy() if solution_depart is not None else None
        self.patients = sorted(instance.patients)
        self.compatibles = [vacations_compatibles(instance.patients[p], instance.vacations) for p in self.patients]
        self.indices_par_chirurgien: dict[int, list[int]] = defaultdict(list)
        for i, p in enumerate(self.patients):
            self.indices_par_chirurgien[instance.patients[p].chirurgien_id].append(i)
        self._cache: dict[tuple, float] = {}

    # ---------------- codage / évaluation ----------------
    def vers_solution(self, individu: Individu) -> SolutionPatients:
        return SolutionPatients(dict(zip(self.patients, individu)))

    def depuis_solution(self, solution: SolutionPatients) -> Individu:
        return [solution.affectations.get(p) for p in self.patients]

    def evaluer(self, solution: SolutionPatients) -> float:
        """Fonction objectif commune du niveau 2."""
        return evaluer_niveau2(self.instance, solution).score_total

    def cout(self, individu: Individu) -> float:
        """Même score que evaluer_niveau2, calculé par l'état incrémental commun (plus rapide)."""
        cle = tuple(individu)
        if cle not in self._cache:
            if len(self._cache) > 200_000:
                self._cache.clear()
            self._cache[cle] = EtatNiveau2(self.instance, dict(zip(self.patients, individu))).score()
        return self._cache[cle]

    def solution_initiale(self, _rng: random.Random) -> SolutionPatients:
        """
        Deux possibilités :

        - données réelles :
          utilisation du planning historique fourni comme solution_depart ;

        - cas général :
          utilisation de la meilleure solution initiale commune au projet.
        """
        if self.solution_depart is not None:
            return self.solution_depart.copy()
        return construire_meilleure_affectation_initiale(self.instance)

    # ---------------- opérateurs génétiques ----------------
    def individu_aleatoire(self, rng: random.Random) -> Individu:
        """Glouton best-fit commun (départages aléatoires) puis quelques déplacements aléatoires."""
        individu = self.depuis_solution(construire_affectation_initiale(self.instance, rng))
        for _ in range(rng.randint(1, max(2, len(individu) // 10))):
            i = rng.randrange(len(individu))
            if self.compatibles[i]:
                individu[i] = rng.choice(self.compatibles[i])
        return individu

    def croiser(self, parent1: Individu, parent2: Individu,
                rng: random.Random) -> tuple[Individu, Individu]:
        enfant1, enfant2 = list(parent1), list(parent2)
        for indices in self.indices_par_chirurgien.values():
            if rng.random() < 0.5:
                for i in indices:
                    enfant1[i], enfant2[i] = parent2[i], parent1[i]
        return enfant1, enfant2

    def muter(self, individu: Individu, rng: random.Random) -> Individu:
        nouveau = list(individu)
        i = rng.randrange(len(nouveau))
        if not self.compatibles[i]:
            return nouveau
        if rng.random() < 0.5:
            # Déplacement vers une autre vacation compatible (jamais vers « non placé »).
            nouveau[i] = rng.choice(self.compatibles[i])
        else:
            # Échange de vacation avec un patient du même chirurgien.
            j = rng.choice(self.indices_par_chirurgien[self.instance.patients[self.patients[i]].chirurgien_id])
            nouveau[i], nouveau[j] = nouveau[j], nouveau[i]
        return nouveau


# =============================================================================
# 4. MOTEUR GÉNÉRIQUE DE L'AGS
# =============================================================================

def _tournoi(population: list[Individu], couts: list[float], taille: int, rng: random.Random) -> Individu:
    """Sélection par tournoi : le meilleur de `taille` individus tirés au hasard."""
    candidats = rng.sample(range(len(population)), min(taille, len(population)))
    return population[min(candidats, key=lambda k: couts[k])]


def _executer_ags(
    probleme: ProblemeGenetique,
    parametres: ParametresAGS,
    suivi: SuiviExecution,
):
    """
    Exécute le moteur générique de l'algorithme génétique.

    Le moteur est identique pour les niveaux 1 et 2.

    Le problème doit uniquement fournir :
        - solution_initiale() / depuis_solution()
        - individu_aleatoire()
        - croiser()
        - muter()
        - cout()

    Le score est MINIMISÉ.
    """

    rng = random.Random(parametres.graine)
    p = parametres

    # -------------------------------------------------------------------------
    # Population initiale : la solution initiale commune + individus aléatoires
    # -------------------------------------------------------------------------

    depart = probleme.depuis_solution(probleme.solution_initiale(rng))
    score_initial = probleme.cout(depart)
    suivi.compter_evaluation()

    population = [depart] + [probleme.individu_aleatoire(rng) for _ in range(p.taille_population - 1)]
    couts = [probleme.cout(ind) for ind in population]
    suivi.compter_evaluation(len(population))

    k = min(range(len(population)), key=lambda i: couts[i])
    meilleur, meilleur_score = list(population[k]), couts[k]

    suivi.enregistrer(iteration=0, score_courant=couts[k], meilleur_score=meilleur_score)

    # -------------------------------------------------------------------------
    # Boucle des générations
    # -------------------------------------------------------------------------

    for generation in range(1, p.generations + 1):

        # Élitisme : les meilleurs individus passent tels quels.
        ordre = sorted(range(len(population)), key=lambda i: couts[i])
        nouvelle = [list(population[i]) for i in ordre[:p.elites]]

        while len(nouvelle) < p.taille_population:
            parent1 = _tournoi(population, couts, p.taille_tournoi, rng)
            parent2 = _tournoi(population, couts, p.taille_tournoi, rng)

            if rng.random() < p.taux_croisement:
                enfant1, enfant2 = probleme.croiser(parent1, parent2, rng)
                suivi.incrementer("croisements")
            else:
                enfant1, enfant2 = list(parent1), list(parent2)

            for enfant in (enfant1, enfant2):
                if rng.random() < p.taux_mutation:
                    enfant = probleme.muter(enfant, rng)
                    suivi.incrementer("mutations")
                if len(nouvelle) < p.taille_population:
                    nouvelle.append(enfant)

        population = nouvelle
        couts = [probleme.cout(ind) for ind in population]
        suivi.compter_evaluation(len(population) - p.elites)

        # ---------------------------------------------------------------------
        # Conservation du meilleur individu rencontré
        # ---------------------------------------------------------------------

        k = min(range(len(population)), key=lambda i: couts[i])
        if couts[k] < meilleur_score:
            meilleur, meilleur_score = list(population[k]), couts[k]

        suivi.enregistrer(iteration=generation, score_courant=couts[k], meilleur_score=meilleur_score)

    return probleme.vers_solution(meilleur), score_initial


# =============================================================================
# 5. RÉSOLUTION DU NIVEAU 1
# =============================================================================

def resoudre_niveau1(
    instance: InstanceProbleme,
    parametres: ParametresAGS | None = None,
) -> ResultatMetaheuristique:
    """
    Applique l'algorithme génétique au niveau 1.

    Retour :
        ResultatMetaheuristique compatible avec les sorties
        RS et Tabou du projet.
    """

    p = parametres if parametres is not None else PARAMETRES_AGS_N1

    probleme = ProblemeGenetiqueNiveau1(instance)

    # Une valeur enregistrée par génération.
    suivi = SuiviExecution(pas_enregistrement=1)

    with suivi:
        solution_finale, score_initial = _executer_ags(probleme, p, suivi)

    return resultat_niveau1(
        "AGS",
        instance,
        solution_finale,
        score_initial=score_initial,
        suivi=suivi,
        parametres=p,
        graine=p.graine,
    )


# =============================================================================
# 6. RÉSOLUTION DU NIVEAU 2
# =============================================================================

def resoudre_niveau2(
    instance: InstanceNiveau2,
    parametres: ParametresAGS | None = None,
    solution_depart: SolutionPatients | None = None,
) -> ResultatMetaheuristique:
    """
    Applique l'algorithme génétique au niveau 2.

    solution_depart :
        - None :
          utilisation de la solution initiale commune du projet ;

        - SolutionPatients :
          permet notamment d'utiliser le planning historique
          comme point de départ sur les données réelles.

    Retour :
        ResultatMetaheuristique compatible avec les sorties
        RS et Tabou du projet.
    """

    p = parametres if parametres is not None else PARAMETRES_AGS_N2

    probleme = ProblemeGenetiqueNiveau2(instance, solution_depart=solution_depart)

    suivi = SuiviExecution(pas_enregistrement=1)

    with suivi:
        solution_finale, score_initial = _executer_ags(probleme, p, suivi)

    return resultat_niveau2(
        "AGS",
        instance,
        solution_finale,
        score_initial=score_initial,
        suivi=suivi,
        parametres=p,
        graine=p.graine,
    )
