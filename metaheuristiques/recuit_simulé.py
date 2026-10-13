# -*- coding: utf-8 -*-
"""
recuit_simule.py
=================

Implémentation du recuit simulé pour les deux niveaux du problème :

Niveau 1 :
    affectation des blocs chirurgiens aux plages opératoires.

Niveau 2 :
    affectation des patients aux vacations.

Les structures de données, fonctions objectif et solutions initiales
communes aux métaheuristiques sont définies dans structures_communes.py.

Les résultats utilisent le format commun défini dans sorties.py.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

# structures_communes.py partagé par tout le dépôt : dossier commun/
_COMMUN = str(Path(__file__).resolve().parents[1] / "commun")
if _COMMUN not in sys.path:
    sys.path.insert(0, _COMMUN)

from structures_communes import (  # noqa: E402
    InstanceNiveau2,
    InstanceProbleme,
    ParametresRecuit,
    ProblemeRecuit,
    SolutionPatients,
    SolutionPlanning,
    construire_meilleure_affectation_initiale,
    evaluer_niveau2,
    evaluer_planning,
    generer_solution_initiale_niveau1,
    plages_possibles_pour_chirurgien,
    vacations_compatibles,
)

from sorties import (
    ResultatMetaheuristique,
    SuiviExecution,
    resultat_niveau1,
    resultat_niveau2,
)


# =============================================================================
# 1. PARAMÈTRES DU RECUIT
# =============================================================================

# Niveau 1 :
# paramètres utilisés dans le prototype du notebook.
#
# Ils ont donné une amélioration du score N1 tout en conservant
# l'absence de conflits de salle et de chirurgien.
PARAMETRES_RS_N1 = ParametresRecuit(
    temperature_initiale=100.0,
    temperature_min=0.01,
    alpha=0.95,
    iterations_par_temperature=100,
    nb_paliers=100,
    graine=42,
)


# Niveau 2 :
# paramètres retenus après calibration sur trois semaines réelles
# représentatives : activité faible, moyenne et forte.
PARAMETRES_RS_N2 = ParametresRecuit(
    temperature_initiale=10_000.0,
    temperature_min=1.0,
    alpha=0.98,
    iterations_par_temperature=50,
    nb_paliers=120,
    graine=42,
)


# =============================================================================
# 2. ADAPTATION DU NIVEAU 1 AU RECUIT
# =============================================================================

class ProblemeRecuitNiveau1(ProblemeRecuit):
    """
    Adaptateur entre le niveau 1 et le moteur de recuit.

    Représentation d'une solution :
        bloc_id -> plage_id

    Voisinage :
        déplacement d'un bloc vers une autre plage compatible
        avec le chirurgien.

    Les éventuels conflits créés par le déplacement sont évalués
    par la fonction objectif commune du niveau 1.
    """

    niveau = 1

    def __init__(self, instance: InstanceProbleme):
        self.instance = instance

    def solution_initiale(
        self,
        rng: random.Random,
    ) -> SolutionPlanning:
        """
        Utilise la solution initiale faisable commune au projet.
        """
        return generer_solution_initiale_niveau1(
            self.instance,
            rng,
        )

    def evaluer(
        self,
        solution: SolutionPlanning,
    ) -> float:
        """
        Fonction objectif commune du niveau 1.
        """
        return evaluer_planning(
            self.instance,
            solution,
        ).score_total

    def voisin(
        self,
        solution: SolutionPlanning,
        rng: random.Random,
    ) -> SolutionPlanning:
        """
        Génère un voisin en déplaçant un bloc vers
        une autre plage compatible.
        """

        nouvelle = solution.copy()

        if not nouvelle.affectations:
            return nouvelle

        # Choix aléatoire d'un bloc à déplacer.
        bloc_id = rng.choice(
            list(nouvelle.affectations)
        )

        bloc = self.instance.blocs_a_placer[
            bloc_id
        ]

        ancienne_plage = nouvelle.affectations[
            bloc_id
        ]

        # Plages compatibles avec ce chirurgien.
        candidats = [
            plage_id
            for plage_id
            in plages_possibles_pour_chirurgien(
                self.instance,
                bloc.chirurgien_id,
            )
            if plage_id != ancienne_plage
        ]

        # Un voisin doit réellement modifier la solution.
        if candidats:
            nouvelle.affectations[
                bloc_id
            ] = rng.choice(candidats)

        return nouvelle


# =============================================================================
# 3. ADAPTATION DU NIVEAU 2 AU RECUIT
# =============================================================================

class ProblemeRecuitNiveau2(ProblemeRecuit):
    """
    Adaptateur entre le niveau 2 et le moteur de recuit.

    Représentation d'une solution :
        patient_id -> vacation_id

    La valeur None signifie qu'un patient est temporairement
    non placé.

    Voisinage :
        modification de l'affectation d'un patient.

    Les dépassements éventuels ne sont pas interdits lors de
    la génération du voisin : ils sont pénalisés par la fonction
    objectif commune du niveau 2.
    """

    niveau = 2

    def __init__(
        self,
        instance: InstanceNiveau2,
        solution_depart: SolutionPatients | None = None,
    ):
        self.instance = instance

        self.solution_depart = (
            solution_depart.copy()
            if solution_depart is not None
            else None
        )

    def solution_initiale(
        self,
        _rng: random.Random,
    ) -> SolutionPatients:
        """
        Deux possibilités :

        - données réelles :
          utilisation du planning historique fourni comme solution_depart ;

        - cas général :
          utilisation de la meilleure solution initiale commune au projet.
        """

        if self.solution_depart is not None:
            return self.solution_depart.copy()

        return construire_meilleure_affectation_initiale(
            self.instance
        )

    def evaluer(
        self,
        solution: SolutionPatients,
    ) -> float:
        """
        Fonction objectif commune du niveau 2.
        """
        return evaluer_niveau2(
            self.instance,
            solution,
        ).score_total

    def voisin(
        self,
        solution: SolutionPatients,
        rng: random.Random,
    ) -> SolutionPatients:
        """
        Génère un voisin en modifiant l'affectation
        d'un patient.
        """

        nouvelle = solution.copy()

        if not self.instance.patients:
            return nouvelle

        # Choix aléatoire du patient.
        patient_id = rng.choice(
            list(self.instance.patients)
        )

        patient = self.instance.patients[
            patient_id
        ]

        ancienne_vacation = (
            nouvelle.affectations.get(
                patient_id
            )
        )

        # Vacations compatibles avec le chirurgien du patient.
        candidats = [
            vacation_id
            for vacation_id
            in vacations_compatibles(
                patient,
                self.instance.vacations,
            )
            if vacation_id != ancienne_vacation
        ]

        # L'état "non placé" appartient à l'espace de recherche.
        #
        # Il est fortement pénalisé par la fonction objectif,
        # mais son existence permet au recuit d'explorerer
        # temporairement une solution moins bonne.
        if ancienne_vacation is not None:
            candidats.append(None)

        if not candidats:
            return nouvelle

        nouvelle.affectations[
            patient_id
        ] = rng.choice(candidats)

        return nouvelle


# =============================================================================
# 4. MOTEUR GÉNÉRIQUE DU RECUIT SIMULÉ
# =============================================================================

def _executer_recuit(
    probleme: ProblemeRecuit,
    parametres: ParametresRecuit,
    suivi: SuiviExecution,
):
    """
    Exécute le moteur générique du recuit simulé.

    Le moteur est identique pour les niveaux 1 et 2.

    Le problème doit uniquement fournir :
        - solution_initiale()
        - evaluer()
        - voisin()

    Le score est MINIMISÉ.
    """

    rng = random.Random(
        parametres.graine
    )

    # -------------------------------------------------------------------------
    # Solution initiale
    # -------------------------------------------------------------------------

    solution = probleme.solution_initiale(
        rng
    )

    score = probleme.evaluer(
        solution
    )

    suivi.compter_evaluation()

    score_initial = score

    meilleure_solution = solution.copy()
    meilleur_score = score

    temperature = (
        parametres.temperature_initiale
    )

    iteration = 0

    suivi.enregistrer(
        iteration=0,
        score_courant=score,
        meilleur_score=meilleur_score,
    )

    # -------------------------------------------------------------------------
    # Boucle des températures
    # -------------------------------------------------------------------------

    for _palier in range(
        parametres.nb_paliers
    ):

        # Plusieurs voisins sont testés à température constante.
        for _ in range(
            parametres.iterations_par_temperature
        ):

            iteration += 1

            voisin = probleme.voisin(
                solution,
                rng,
            )

            score_voisin = probleme.evaluer(
                voisin
            )

            suivi.compter_evaluation()

            # Delta > 0 :
            # le voisin est moins bon car le score est minimisé.
            delta = (
                score_voisin
                - score
            )

            # -----------------------------------------------------------------
            # Règle de Metropolis
            # -----------------------------------------------------------------

            accepte = False

            # Une amélioration est toujours acceptée.
            if delta <= 0:
                accepte = True

            # Une dégradation peut être acceptée avec une probabilité
            # dépendant de la température.
            else:
                probabilite = math.exp(
                    -delta / temperature
                )

                if rng.random() < probabilite:
                    accepte = True

                    suivi.incrementer(
                        "degradations_acceptees"
                    )

            if accepte:

                solution = voisin
                score = score_voisin

                suivi.incrementer(
                    "mouvements_acceptes"
                )

            # -----------------------------------------------------------------
            # Conservation du meilleur état rencontré
            # -----------------------------------------------------------------

            if score < meilleur_score:

                meilleure_solution = (
                    solution.copy()
                )

                meilleur_score = score

            suivi.enregistrer(
                iteration=iteration,
                score_courant=score,
                meilleur_score=meilleur_score,
            )

        # ---------------------------------------------------------------------
        # Refroidissement géométrique
        # ---------------------------------------------------------------------

        temperature *= (
            parametres.alpha
        )

        if (
            temperature
            < parametres.temperature_min
        ):
            break

    return (
        meilleure_solution,
        score_initial,
    )


# =============================================================================
# 5. RÉSOLUTION DU NIVEAU 1
# =============================================================================

def resoudre_niveau1(
    instance: InstanceProbleme,
    parametres: ParametresRecuit | None = None,
) -> ResultatMetaheuristique:
    """
    Applique le recuit simulé au niveau 1.

    Retour :
        ResultatMetaheuristique compatible avec les sorties
        Tabou et AGS du projet.
    """

    p = (
        parametres
        if parametres is not None
        else PARAMETRES_RS_N1
    )

    probleme = ProblemeRecuitNiveau1(
        instance
    )

    # Une valeur enregistrée environ une fois par palier.
    suivi = SuiviExecution(
        pas_enregistrement=
        p.iterations_par_temperature
    )

    with suivi:

        solution_finale, score_initial = (
            _executer_recuit(
                probleme,
                p,
                suivi,
            )
        )

    return resultat_niveau1(
        "RS",
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
    parametres: ParametresRecuit | None = None,
    solution_depart: SolutionPatients | None = None,
) -> ResultatMetaheuristique:
    """
    Applique le recuit simulé au niveau 2.

    solution_depart :
        - None :
          utilisation de la solution initiale commune du projet ;

        - SolutionPatients :
          permet notamment d'utiliser le planning historique
          comme point de départ sur les données réelles.

    Retour :
        ResultatMetaheuristique compatible avec les sorties
        Tabou et AGS du projet.
    """

    p = (
        parametres
        if parametres is not None
        else PARAMETRES_RS_N2
    )

    probleme = ProblemeRecuitNiveau2(
        instance,
        solution_depart=solution_depart,
    )

    suivi = SuiviExecution(
        pas_enregistrement=
        p.iterations_par_temperature
    )

    with suivi:

        solution_finale, score_initial = (
            _executer_recuit(
                probleme,
                p,
                suivi,
            )
        )

    return resultat_niveau2(
        "RS",
        instance,
        solution_finale,
        score_initial=score_initial,
        suivi=suivi,
        parametres=p,
        graine=p.graine,
    )