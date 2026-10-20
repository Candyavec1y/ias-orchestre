# Paramètres réellement exécutés (commit `d8fbf35`)

Valeurs lues dans le code (`commun/parametres.py`, `commun/structures_communes.py`,
`metaheuristiques/hybridation.py`, `sma/sma_urgences.py`). Les tailles d'instances mesurées sont dans
`instances.csv`.

## 1. Instances

| Famille | Instance | Contenu |
|---|---|---|
| N1 | instance d'étude **fictive** (`construire_instance_etude`) | 8 chirurgiens, 3 salles, semaine du 21/09/2026, créneaux de 2 h (8-10, 10-12, 13-15, 15-17) ; 60 plages (3 salles × 20 créneaux), dont 5 réservées aux urgences (salle 3, 8-10 h) ; 45 blocs de 2 h à placer (besoins 14 + 14 + 8 + 8 + 14 + 8 + 8 + 16 = 90 h) ; disponibilités élargies (version Tabou) |
| N2 | planning **réel v28**, 4 semaines à partir du 12/10/2026 (`hybridation.instance_v28`) | 144 vacations régulières, 23 chirurgiens, 4 salles, cycle de parité des semaines ; + 3 semaines de report ajoutées après l'horizon (`etendre_horizon`, vacations du planning v28) ; capacité utile = 90 % de chaque vacation (marge de 10 %) ; 30 lits dont 3 de réserve (27 programmables), 20 places ambulatoires par demi-journée |
| N2 charges | même planning, charge du générateur `c` constante sur les 4 semaines | 70 / 85 / 100 / 115 % de la capacité utile visés → `c` = 0,63 / 0,765 / 0,90 / 1,035 (le générateur exprime la charge en fraction des heures de vacation ; ratio réellement obtenu dans `instances.csv`) |
| SMA | planning v28, 2 semaines (scénarios) | `sma_urgences.construire_instances_v28`, capacités 30 / 3 / 20, programme initial glouton |
| Saturation | planning v28, programme initialement vide | patients au profil de séjours réels (`saturation.tirer_patients_profils_reels`) inscrits un par un et placés par le SMA |
| ML | `donnees_hospitalieres.csv` | voir `ml_resume.md` |

## 2. Patients

| Générateur | Utilisé pour | Distributions | Graines |
|---|---|---|---|
| `generer_patients_etude` (synthétique) | N1 / N2 de l'étude, N2 v28, SMA | durée uniforme dans {30, 45, 60, 75, 90, 105, 120, 150} min ; 40 % d'ambulatoires ; hospitalisé : 1 nuit avant dans 30 % des cas, 1 / 1 / 2 / 2 / 3 nuits après ; priorités 1 / 2 / 3 / 4 : 15 / 50 / 25 / 10 %, 5 % d'urgences (priorité 4) ; date au plus tôt : lundi de la semaine | cohortes 43 (référence, `GRAINE_PATIENTS`), 44, 45 ; + 97 par semaine |
| `tirer_patients_profils_reels` | saturation | durée, mode et nuits d'un séjour réel tiré au hasard (en mémoire) ; chirurgien au prorata du temps de vacation ; priorité 2 | `GRAINE_SATURATION` = 42 |
| `urgences_semaine_aleatoire` | scénarios SMA aléatoires | jour, heure, durée, mode, nuits calibrés 2019-2022 ; gravités (10 / 20 / 70 %) et spécialités : hypothèses | `GRAINE_SCENARIOS_SMA` = 1 |

**Les patients N2 ne viennent pas du ML** : ils sont synthétiques. Seuls les patients saisis en consultation sur
le site ont des durées et des nuits prédites par le ML.

## 3. Fonctions objectif (à minimiser)

**F1 (N1, `evaluer_planning`)** = 10 000 × conflits de salle + 10 000 × conflits de chirurgien + 100 × salles
différentes par chirurgien + 50 × fragmentation (blocs non contigus d'un chirurgien dans une journée). Faisabilité
N1 (validateur `valider_niveau1`) : tous les blocs placés, plage existante et LIBRE, salle autorisée, chirurgien
disponible, aucun conflit, besoins horaires couverts.

**F2 commun (N2, `evaluer_niveau2`)** = 8 000 × patients non placés + 100 × minutes au-delà de la capacité utile
+ 1 × minute inoccupée (vacations régulières) + 5 000 × lit-nuit au-delà de la capacité + 20 × variance de
l'occupation des lits + 5 000 × place-demi-journée au-delà de la capacité + 20 × variance de l'occupation des
places. Composantes publiées : score bloc, score lits, score places.

**Score de recherche N2** = F2 commun + pénalité de report = 100 × poids de priorité (1 / 2 / 3 / 5 pour les
priorités 1 / 2 / 3 / 4) × semaines après la fin de l'horizon. Les méthodes optimisent le score de recherche ;
**les comparaisons utilisent F2 commun** ; les deux sont publiés (`score_commun`, `score_recherche`,
`penalite_report`).

**Faisabilité N2** (validateur indépendant `valider_niveau2`) : affectation, vacation existante, bon chirurgien,
date au plus tôt, capacité utile de chaque vacation, lits par nuit, places par demi-journée. Le dépassement de la
capacité utile d'une vacation est une **pénalité** dans F2 mais une **violation** pour le validateur.

## 4. Méthodes

Départ commun : N1 = solution initiale du problème (graine) ; N2 = glouton best-fit multi-départ (40 essais) puis
`placer_restants` (chaque patient restant dans la vacation qui dégrade le moins le score, report compris). Budget :
**10 s de temps réel par exécution** (étude de budget : 2, 5, 20 s).

| Méthode | Paramètres |
|---|---|
| RS seul | T0 calibré pour accepter 30 % des dégradations typiques, T_fin = T0 × 10⁻³, refroidissement géométrique sur le budget |
| TABOU seul | durée taboue 25 + aléa 0-5, patience 40 itérations avant perturbation (N2 : 15-30 mouvements ; N1 : 2-5), voisinage N1 150 voisins ; N2 300 échanges + 80 insertions avec éjection par itération |
| AGS seul | population 30, tournoi 3, croisement 0,9, mutation 0,4, 2 élites, doublons re-mutés, générations bornées par le temps, aucune recherche locale |
| memetique | AGS + Tabou (15 itérations) sur les 2 meilleurs enfants de chaque génération ; 25 % du temps final : RS (50 %) puis Tabou |
| AGS>RS>TABOU | AGS sans recherche locale sur 50 % du temps, puis RS > Tabou sur le meilleur |
| RS>AGS>TABOU | 40 % du temps : 4 recherches locales RS > Tabou depuis 4 départs différents (population initiale) ; puis AGS mémétique ; 25 % final RS > Tabou |
| glouton | départ commun (aucune recherche) |
| premier créneau | adaptateur isolé du script de campagne : patients par date au plus tôt puis priorité décroissante, dans la première vacation compatible qui respecte capacité utile, lits et places ; sinon non placé |

## 5. SMA

Paramètres par défaut de `ParametresSMA` : pas de 5 min ; brancardage 20 min ; salle de réveil 60 min ; gravités
vitale / urgente / différable : délai 60 / 360 / 1 440 min, tolérance 60 / 180 / 240 min ; garde 18 h - 8 h ;
optimisation locale « TABOU seul » 0,02 s par créneau ; optimisation globale « memetique » 1 s, gain minimal 50 ;
prévenance d'absence 2 jours ; alerte de report au-delà de 3 jours. **Configuration du site** : optimisations
locale et globale désactivées (`ParametresSMA(optimisation_globale=None, methode_locale=None)`).

## 6. Occupation

Lits : par nuit, sortie à midi, réutilisables le jour même après 1 h de remise en état. Places ambulatoires : par
demi-journée (matin si l'intervention ou la vacation commence avant 13 h), 1 h de remise en état entre les deux
patients d'une place. Le modèle ne contient pas d'heure d'admission du soir : les courbes lits matin / soir ne
sont pas mesurables (seulement nuitées et sorties du jour).
