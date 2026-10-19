# -*- coding: utf-8 -*-
"""
commun/parametres.py — PARAMÈTRES DU PROJET
============================================

Chaque valeur partagée par plusieurs modules est définie ICI, une seule fois ; les modules l'importent au lieu de
la réécrire. Ce fichier ne dépend d'aucun autre (simples constantes) : structures_communes.py en construit les
objets (ParametresHebergement…).
"""
from datetime import date

# =============================================================================
# Capacités d'hébergement (par jour)
# =============================================================================
# Application et planning réel v28 (interface, SMA, scénarios, hybridation sur v28, tests, saturation).
# L'administrateur peut les modifier depuis l'interface (Administration -> Lits et places).
LITS_SITE = 30                                # lits d'hospitalisation au total...
RESERVE_LITS_SITE = 3                         # ... dont réservés aux urgences (27 programmables)
PLACES_AMBULATOIRES_SITE = 20

# Instance d'étude du niveau 1 (8 chirurgiens, 3 salles, créneaux de 2 h) : petite instance expérimentale,
# à ne pas confondre avec les capacités de l'application.
LITS_INSTANCE_ETUDE_N1 = 14
RESERVE_LITS_INSTANCE_ETUDE_N1 = 2
PLACES_AMBULATOIRES_INSTANCE_ETUDE_N1 = 10

# =============================================================================
# Budget de calcul
# =============================================================================
# Secondes par méthode pour l'optimisation du programme (interface : premier lancement et recalcul ;
# hybridation.py en ligne de commande, modifiable par --temps). Même budget pour toutes les méthodes.
BUDGET_OPTIMISATION_S = 10.0
# (les budgets du SMA, locaux et globaux, sont dans sma_urgences.ParametresSMA : budget_local_s, budget_global_s)

# =============================================================================
# Graines (reproductibilité) — tout script en ligne de commande accepte --graine
# =============================================================================
GRAINE_ETUDE = 42                 # recherche (métaheuristiques), solution initiale N1, instance d'étude
GRAINE_PATIENTS = GRAINE_ETUDE + 1  # générateur de patients des instances synthétiques (generer_patients_etude)
DECALAGE_GRAINE_PRIORITES = 1000  # generer_patients_etude : priorités tirées avec graine + 1000 (second générateur)
PAS_GRAINE_SEMAINE = 97           # semaine k d'un horizon : graine = GRAINE_PATIENTS + PAS_GRAINE_SEMAINE x k
GRAINE_POPULATION_N1 = 1000       # individus supplémentaires de la population AGS N1 : graine + k
GRAINE_MESA = 42                  # modèle Mesa du SMA
GRAINE_SCENARIOS_SMA = 1          # scénarios aléatoires du SMA (semaine_normale, semaine_surcharge)
GRAINE_ML = 42                    # séparation entraînement / test et modèles de machine learning
GRAINE_SATURATION = 42            # tirage des patients de l'étude de saturation

# =============================================================================
# Horizons (en semaines)
# =============================================================================
LUNDI_REFERENCE = date(2026, 10, 12)   # premier lundi des instances v28 de référence (tests, saturation, campagnes)

# -----------------------------------------------------------------------------
# =============================================================================
NB_SEMAINES_HORIZON = 4           # interface : semaines du programme optimisé (patients de démonstration)
NB_SEMAINES_SMA = 52              # interface : semaines connues du SMA (planning fixe ; au-delà des 4 semaines
                                  # optimisées, semaines ouvertes sans patient de démonstration)
NB_SEMAINES_SCENARIOS_SMA = 2     # scénarios du SMA (sma/scenarios_sma.py)
NB_SEMAINES_REPORT = 3            # hybridation : semaines AJOUTÉES APRÈS l'horizon de l'instance, ouvertes au
                                  # report des patients (vacations dupliquées, pénalité de report)

# Programme de démonstration de l'interface (et instance v28 par défaut des campagnes d'hybridation) : charge
# déjà programmée semaine par semaine, en fraction des heures de vacation (un programme se remplit à l'approche
# de la date). Bornes (min, max) passées à generer_patients_etude ; au-delà, la dernière valeur.
CHARGES_PAR_SEMAINE = ((0.85, 1.00), (0.60, 0.75), (0.35, 0.50), (0.10, 0.25))
CHARGE_GENERATEUR = (0.90, 1.10)  # charge par défaut de generer_patients_etude (instance d'étude, scénarios du SMA)

# =============================================================================
# Bloc et coûts partagés
# =============================================================================
TAUX_MARGE_VACATION = 0.10        # part de chaque vacation réservée aux aléas (capacité utile = 90 %)
COUT_LIT_EN_TROP = 5000.0         # par lit x jour au-delà de la capacité : MÊME valeur dans la fonction objectif
                                  # N2 (PoidsNiveau2.lit) et dans les coûts du SMA (ParametresSMA.c_lit_depassement)
