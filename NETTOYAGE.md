# Nettoyage du code — compte rendu

Branche `nettoyage`, partie de `main` (72d3c26). Un commit par lot (`nettoyage: lot N — …`). Au départ :
93 tests rapides, tous verts. À la fin : 138 tests rapides et 2 tests lents, tous verts (voir « Vérification
finale »).

Les points qui demandent une décision de l'équipe sont repris à la fin, dans « Points à trancher ».

---

## Lot 1 — Fichiers et code morts

**Fait**
- Supprimés : `metaheuristiques/tabou_fonctionnel/`, `affichage_planning.py`, `machine_learning/creation_patients.py`,
  `metaheuristiques/recuit_simulé.py`, `metaheuristiques/algorithme_genetique.py`.
- `structures_communes.py` : sections propres au recuit et au tabou autonomes retirées (`ParametresRecuit`,
  `ProblemeRecuit`, `ParametresTabou`, `ParametresVacationsSupplementaires`, `ProblemeTabou`),
  `calculer_f_priorite` et le poids inutilisé `PoidsNiveau2.priorite` (D11) ; `sorties.py` utilise
  `penalite_priorite_patient`.
- `test_metaheuristiques.py` réécrit sur les modes de `hybridation.py` (RS seul, TABOU seul, AGS seul) sans rien
  enlever de ce qui était vérifié ; un test ajouté : l'état incrémental du niveau 2 donne le même score que la
  fonction objectif.

**Décisions appliquées** : D1, D3, D11.

**À savoir (D3)** : paramètres « calibrés » des fichiers supprimés, à comparer avec ceux de l'hybridation :

| | recuit_simulé.py | algorithme_genetique.py | hybridation.py (RS seul / AGS seul) |
|---|---|---|---|
| N1 | T0 100, Tmin 0,01, α 0,95, 100 it./palier, 100 paliers | pop. 40, 150 gén., croisement 0,8, mutation 0,3, tournoi 3, 2 élites | T0 calibré (30 % d'acceptation), T_fin = T0 × 10⁻³, budget en secondes ; AGS pop. 30, croisement 0,9, mutation 0,4, tournoi 3, 2 élites |
| N2 | T0 10 000, Tmin 1, α 0,98, 50 it./palier, 120 paliers | pop. 30, 120 gén., croisement 0,8, mutation 0,4 | idem |

Différences : budget en itérations contre budget en temps, T0 fixé contre T0 calibré, taille et taux de l'AGS.

`sorties.calculer_indicateurs_niveau2` recopiait la pénalité de priorité sans le cas « urgence → 4 » ni le bornage
1..4 : résultat identique en pratique (urgences déjà en priorité 4, priorités toujours dans 1..4).

## Lot 2 — Noms de fichiers et références obsolètes

**Fait**
- `hybridage2.py` → `hybridation.py` (`git mv`) ; imports mis à jour (`programme.py`, `metaheuristiques_sma.py`,
  tests), faux `try/except` d'import supprimé.
- Hybridation : en-tête corrigé, branche `jeux_de_donnees` supprimée (`--jeu` n'accepte plus que `etude`),
  « optimum connu de l'étude : 900 » supprimé (aussi dans `CHOIX.md`).
- `sma_urgences.py` : chemin `commun/structures_communes.py`, référence à `comparer_metaheuristiques_sma.py`
  retirée ; « Mesa >= 3.0 » déjà aligné sur `requirements.txt`.
- `structures_communes.py` : en-tête (notebooks absents retirés, horizon de plusieurs semaines, capacités 14/2/10
  attribuées à l'instance d'étude du niveau 1).
- `modele_prediction_rapide.py` : mention de `modeles_prediction.py` retirée.
- `programme.comparer_algorithmes_n2` supprimée (jamais appelée ; les campagnes passent par `hybridation.py`).

**Décisions appliquées** : D2, D6 (valeurs d'optimum). La commande `grep` du lot ne renvoie plus rien.

## Lot 3 — Paramètres définis une seule fois

**Fait** : `commun/parametres.py` regroupe capacités, budget, graines, horizons et quelques constantes partagées
(`TAUX_MARGE_VACATION`, `COUT_LIT_EN_TROP`, heure de sortie, remise en état). `structures_communes.py` construit
`HEBERGEMENT_SITE` (30 lits / 3 de réserve / 20 places) et `HEBERGEMENT_INSTANCE_ETUDE_N1` (14 / 2 / 10) ;
`programme.HEBERGEMENT_V28` est supprimé. `scenarios_sma.py` accepte `--graine` (les autres scripts l'acceptaient
déjà). Les budgets temps réel du SMA (`BUDGET_LOCAL_SMA_S` 0,02 s, `BUDGET_GLOBAL_SMA_S` 1 s) ont rejoint le
fichier lors de la vérification finale.

**Décision appliquée** : D4.

**Changements de comportement**
- Les scénarios du SMA utilisaient `ParametresHebergement()` = 14 / 2 / 10 ; ils utilisent maintenant les
  capacités du site 30 / 3 / 20 (D4). Leurs bilans peuvent changer (moins de refus de lits).
- Budget : 20 s en ligne de commande et dans `ParametresHybride`, 15 s par défaut dans `calculer_programme`, 10 s
  dans l'interface. Valeur unique retenue : **10 s**, celle que le site utilise réellement. Le défaut de
  `hybridation.py` passe donc de 20 à 10 s (`--temps 20` pour revenir à 20 s).

**Laissé volontairement** : `test_capacites.PETITE` (12 lits) est un scénario de test, pas un paramètre.

## Lot 4 — Générateurs de patients (D7)

**Fait** : les trois générateurs sont gardés séparés (objectifs différents) et documentés : objectif,
distributions (observées ou hypothèses), graines.
- `generer_patients_etude` : instances synthétiques d'optimisation ; décalage de graine des priorités nommé
  `DECALAGE_GRAINE_PRIORITES`.
- `saturation.tirer_patients` → `tirer_patients_profils_reels` : profils de séjours réels lus en mémoire, aucun
  export.
- `scenarios_sma.semaine_aleatoire` → `urgences_semaine_aleatoire` : bloc « PROFIL DES URGENCES » documenté.

**Vérifié** : patients tirés identiques avant / après pour trois graines. Aucune distribution modifiée.

## Lot 5 — Instance v28, validateur, sorties complètes, reports

**Fait**
- 5.1 `hybridation.py` : `--instance v28` (par défaut, niveau 2) ou `etude`, `--lundi`, `--semaines`,
  `--patients N` ou `--charge x`, `--temps`, `--graine`, `--graines` (un JSON par méthode et par graine). Le niveau
  1 reste sur l'instance d'étude (D6) ; le chaînage N1 → N2 n'existe que sur l'instance d'étude. Un seul
  constructeur v28 : `programme.construire_instances` appelle `sma_urgences.construire_instances_v28`.
  Instances de l'interface et du SMA vérifiées identiques avant / après.
- D10 : `ResultatMetaheuristique.score_recherche` et `detail_score["report"]` enregistrés dans les JSON.
- 5.2 `commun/validation.py`, indépendant des fonctions objectif et des algorithmes. Niveau 1 : affectation, plage
  existante ou LIBRE, salle autorisée, disponibilité, conflits de salle et de chirurgien, besoins horaires. Niveau
  2 : affectation, vacation existante, chirurgien, date au plus tôt, capacité utile, lits, places. Le résultat
  (faisable, violations par type) accompagne chaque résultat et le programme de l'interface. La meilleure
  solution hybride retenue est une solution faisable ; sinon elle est signalée « NON VALIDE ». Dans l'interface,
  la régulation et l'administrateur voient un bandeau rouge et la liste des contraintes violées.
- 5.3 (R1) : incohérence confirmée dans `etendre_horizon` sur une instance de plusieurs semaines. Chaque vacation
  décalée de k semaines recouvrait les semaines suivantes (312 vacations en double sur v28, 4 semaines). Correction :
  la semaine de report k reprend la semaine (k−1) mod W de l'horizon, placée en semaine W+k−1. Pour W = 1
  (instance d'étude), le comportement ne change pas. Le site n'étendait pas l'horizon : il n'était pas touché.

**Décisions appliquées** : D5, D6, D9, D10, R1.

**Défaut trouvé par le validateur (corrigé)** : les **échanges** de deux patients du même chirurgien (voisinage
tabou, mutation AGS, mouvement du recuit) ne vérifiaient pas que chacun pouvait recevoir la vacation de l'autre.
Le mode mémétique plaçait **51 patients avant leur date au plus tôt**, cas que la fonction objectif ne pénalise
pas. Correction minimale : `ProblemeHybrideN2.echange_possible`. Après correction, les 6 méthodes donnent des
solutions faisables et leurs scores sont quasi identiques (mémétique 13 604 contre 13 586). La fonction
objectif n'a pas changé. Un test de non-régression est ajouté.

**Conséquence pour le site** : le programme enregistré dans la base (mode mémétique, calculé le 12/10) est **non
valide** (54 patients avant leur date au plus tôt). L'onglet Planning l'affiche. Il faut le recalculer :
Administration → Lits et places → Recalculer.

**Non modifié** : la sélection à l'intérieur d'une recherche (AGS, recherche locale) ; elle relève des stratégies
d'hybridation, hors périmètre.

**Tests ajoutés** : `test_validation.py`, `test_reports.py`.

## Lot 6 — Convention d'occupation des lits (Q13)

**Fait** : une seule fonction de décompte (aujourd'hui `periodes_occupation`) et l'intervalle daté `intervalle_lit`
(`commun/structures_communes.py`). Les utilisent : le niveau 2, `EtatNiveau2`, l'agent Hébergement du SMA,
l'optimisation globale du SMA, les indicateurs, l'étude de saturation et le validateur.
- Hospitalisé : décompte par **nuitée**, de l'admission (jour J moins les nuits avant) à la veille de la sortie
  (J plus les nuits après, à midi, `HEURE_SORTIE_HOSPITALISATION` = 12). Le jour de sa sortie, le patient n'est plus
  compté. Un lit n'est réattribué qu'après midi plus la remise en état (`DUREE_REMISE_EN_ETAT_LIT_MIN` = 60 min,
  confirmée ensuite par l'équipe) : jamais deux patients à la fois dans un lit. Hospitalisé sans nuitée : un lit le jour de
  l'intervention.
- Poids de la fonction objectif inchangés.

**Valeurs qui changent (avant → après)**
- programme de démonstration (glouton, 4 semaines) : score 14 209 → 13 910, pic de lits 25 → 15, occupation des
  lits 52,0 % → 35,8 % ;
- instance d'étude (glouton) : score 113 166 → 113 030, pic de lits 12 → 10 ;
- étude de saturation (4 semaines) : capacité 438 → 431 patients ; les lits ne sont plus jamais pleins ; la
  ressource limitante reste le temps opératoire.

**Places ambulatoires** : laissées à la journée entière pendant le lot, puis découpées en demi-journées sur
décision de l'équipe (voir « Décisions prises après le nettoyage »).

**Test ajouté** : `test_occupation.py`.

## Lot 7 — Machine learning factorisé, urgence par règle (D8)

**Fait**
- `machine_learning/preparation.py`, utilisé par les deux scripts et par l'interface :
  - préparation des données ;
  - `regle_urgence`, fonction unique ;
  - un seul découpage 80/20 stratifié (graine `GRAINE_ML`) ;
  - évaluation commune : tailles réelles, MAE / RMSE / R², accuracy, F1 par classe, matrice de confusion ;
  - nuits avant et après apprises **et évaluées** sur les hospitalisés du même découpage.
- `reg_urgence.joblib` et son entraînement sont supprimés. La priorité vient de la règle (même conversion score →
  priorité) ; le médecin la valide ou la corrige. Dans l'interface, « Score d'urgence » devient « Priorité
  proposée (règle du projet, non validée cliniquement) ».
- `utilisation_modèle.py` → `utilisation_modele.py`. Supprimés car inutilisés : `chemins.importer_fichier` et
  `DOSSIER_MODELES_ML`. Options `--graine` (les deux scripts) et `--evaluer-seulement`.

**Vérifié** : préparation identique à l'ancienne (même tableau, 14 477 séjours). Les modèles ré-entraînés en
mémoire donnent les mêmes prédictions que ceux de production : **aucun ré-entraînement**, `.joblib` et
`donnees_hospitalieres.csv` inchangés.

**Valeurs affichées qui changent (Consultation)** : les nuits après sont maintenant évaluées sur les seuls
hospitalisés. Avant, les ambulatoires comptaient avec 0 nuit, prédiction facile qui flattait le score. MAE 0,32 →
0,54 ; ±1 nuit 90,5 % → 85,1 %. Capacité (92,5 %) et durée au bloc (R² 0,67) : inchangées.

**Décision appliquée** : D8.

## Lot 8 — Système multi-agent

**Fait**
- 8.1 Absence : événement `AbsenceChirurgien(heure, chirurgien_id, du, au, motif)` traité par la Régulation, avec
  le même comportement qu'avant ; les délais vont dans `ParametresSMA` (`prevenance_absence_jours` = 2,
  `seuil_alerte_report_jours` = 3). `sma_service.py` ne fait plus que convertir l'événement de la base.
  `test_absences.py` vérifie toujours la même chose ; seule la source des deux constantes change. Nouveau scénario :
  `absence_chirurgien`.
- 8.2 Transfert (D12) :
  - `ParametresSMA.specialites_garde`, par défaut la spécialité du service ; l'équipe de garde n'est sollicitée
    que pour une spécialité couverte ;
  - nouveau niveau d'escalade 5, « transfert » : décision `urgence_transferee` et alerte « décision humaine requise
    : transfert proposé » ;
  - s'il existe un meilleur plan interne, il est appliqué en attendant la décision du régulateur ; le SMA ne
    retire jamais le patient de lui-même ;
  - nouveau compteur `urgences_transferees` dans le bilan, lu par la colonne « transférées » de `tester_tous` ;
  - les urgences transférées ne comptent plus parmi les urgences non programmées.
- 8.3 a) `ProlongationIntervention(heure, patient_id, minutes_supplementaires)` :
  - la salle réordonne la suite du créneau à partir de la nouvelle fin, avec les coûts de décalage existants ;
  - les patients qui ne tiennent plus dans les heures du créneau sont déprogrammés puis replacés (appel d'offres,
    liste d'attente) ;
  - si l'intervention prolongée dépasse elle-même la fin du créneau, le dépassement est enregistré et toléré par
    le contrôle de cohérence (on n'arrête pas une intervention commencée) ;
  - salle de réveil et brancardage (panne éventuelle du monte-lit) sont pris en compte ;
  - formulaire dans Urgences → Incident logistique (un chirurgien ne voit que ses interventions).
- 8.3 b) `IndisponibiliteLits(heure, nb_lits, du, au, motif)` :
  - l'agent Hébergement réduit la capacité sur la période, avec la convention du lot 6 ;
  - pour chaque jour en dépassement, sont déprogrammés les hospitalisés non commencés et non urgents : priorité
    la plus faible d'abord, puis intervention la plus tardive ;
  - ils sont replacés par l'appel d'offres existant ; l'Hébergement refuse les jours encore pleins
    (`cap_lits_jour`), ce qui tient lieu de `jours_exclus` ;
  - la liste d'attente est relancée le lendemain de la fin de la période ;
  - formulaire réservé au cadre de bloc et à l'administrateur.
- **Lits ou réserve en premier ?** L'indisponibilité touche **d'abord les lits programmables**. La réserve des
  urgences reste entière tant qu'il reste au moins autant de lits que la réserve. Les urgences peuvent donc
  toujours utiliser la réserve.
- Nouveaux scénarios : `absence_chirurgien`, `prolongation_intervention`, `lits_indisponibles`. Avec `--tous`, la
  cohérence est OK pour les 15 scénarios.

**Changement de scénarios (à valider)** : les spécialités des urgences des scénarios (« Orthopédie », « Main »,
« Rachis ») ne correspondaient à aucune spécialité du service ; avec `specialites_garde`, elles auraient toutes
été transférées. Elles sont alignées sur la spécialité du service. Seule « Vasculaire » (scénario
`chirurgien_absent`) reste hors service : elle produit 1 transfert proposé. Les textes « attendu » des scénarios
sont réécrits d'après les résultats réellement obtenus.

**Décisions appliquées** : D12, D13.

**Tests ajoutés** :
- `test_aleas_sma.py` (8 tests) :
  - prolongation : décalage simple, dépassement du créneau avec replacement, prolongation pendant une panne ;
  - lits : capacité jamais dépassée et retour à la normale, faible priorité déplacée d'abord, réserve gardée pour
    les urgences ;
  - transfert : proposé pour une spécialité non couverte, comportement inchangé sinon ;
- `test_interface.py` : déclaration d'une prolongation par un chirurgien et de lits indisponibles par la
  régulation.

## Lot 9 — Documentation

**Fait** : mise à jour de `README.md`, `interface/README.md`, `interface/CHOIX.md` et `interface/tests/README.md` :
liste des fichiers, nom de l'hybridation, capacités (D4), séparation des niveaux (D6), générateurs (D7), règle
d'urgence (D8), validateur (D9), convention d'occupation (Q13), aléas gérés, commandes, nouveaux tests.

Affirmations fausses retirées : « 5 modèles », `creation_patients.py`, `utilisation_modèle.py`, « le SMA ne
connaît que 5 spécialités », dossier `SMA/`, liste d'attente présentée comme l'issue normale, maquettes
« non modifiées » qui ne sont plus dans le dépôt. Aucune valeur d'optimum ne reste.

### Passages du rapport à mettre en cohérence

Le rapport n'est pas dans le dépôt et n'a pas été modifié. À reprendre :
1. **D6, séparation des niveaux** : tout passage qui présente le niveau 1 comme optimisé sur le planning réel, ou
   un chaînage N1 → N2 → SMA sur v28. Le N1 est étudié sur l'instance fictive (8 chirurgiens, 3 salles, 14 / 2 /
   10) ; le N2 et le SMA tournent sur v28 avec 30 lits (dont 3 de réserve) et 20 places. Résultats et tableaux de
   capacités sont à étiqueter selon l'instance.
2. **D6, optimum** : toute mention d'un « optimum connu » (900) de l'instance d'étude.
3. **D8, urgence** : toute mention d'un modèle de prédiction du score d'urgence, de son R² ou de « 5 modèles ». Le
   score vient d'une règle CIM-10 / CCAM, non validée cliniquement, et donne une priorité proposée que le médecin
   valide.
4. **D8, métriques** : les métriques des nuits après (MAE 0,54, ±1 nuit 85,1 %, sur les hospitalisés), qui
   remplacent les anciennes (0,32 / 90,5 %).
5. **Q13, occupation** : toute définition de l'occupation d'un lit ou d'une place « par jour calendaire ». Les lits
   se comptent par nuitée (sortie à midi, remise en état de 60 min) ; les places par demi-journée (matin /
   après-midi, remise en état de 60 min). Les chiffres d'occupation changent (pics, taux, capacité de saturation
   438 → 432 patients, voir lot 6 et « Décisions prises après le nettoyage »).
6. **Lot 5** : les résultats du mode mémétique obtenus avant la correction des échanges (patients placés avant
   leur date au plus tôt) sont à recalculer.

---

## Décisions prises après le nettoyage

- **Budget** : 10 s pour le site, confirmé.
- **Remise en état d'un lit** : 1 h par le service de nettoyage, confirmé. Ce n'est plus une hypothèse.
- **Spécialités des scénarios du SMA** : l'alignement sur le service est validé.
- **Places ambulatoires par demi-journée** (avec 1 h de remise en état entre deux patients) :
  - une seule fonction, `periodes_occupation` (qui remplace `jours_occupation`) : nuits (dates) pour les lits,
    `DemiJournee(jour, apres_midi)` pour les places ;
  - un patient est du matin si son intervention commence avant 13 h, de l'après-midi sinon
    (`HEURE_DEBUT_APRES_MIDI_AMBULATOIRE`). Le niveau 2 classe selon le début de la vacation, le SMA selon le début
    de l'intervention ; sur v28 les deux coïncident (matinées jusqu'à 13 h, après-midi dès 13 h 30) et un test le
    vérifie ;
  - `intervalle_place` : le patient du matin libère sa place à 13 h ; elle est prête pour l'après-midi à 14 h
    (`DUREE_REMISE_EN_ETAT_PLACE_MIN` = 60). Une place sert donc à deux patients par jour, jamais en même temps ;
  - les capacités se vérifient par demi-journée : fonction objectif (dépassement, variance, taux), état incrémental,
    agent Hébergement, optimisation globale du SMA, validateur (violation « places ambulatoires » datée
    « AAAA-MM-JJ matin / après-midi »). À l'affichage et dans les sorties JSON, l'occupation des places par jour est
    le **pic de la journée** (`par_jour`). Poids inchangés.
  - valeurs qui changent (avant → après) : programme de démonstration (glouton) score 13 910 → 13 820, pic de
    places 10 → 6, taux d'occupation des places 30,5 % → 19,7 % (calculé maintenant par demi-journée occupée) ;
    instance d'étude (glouton) 113 030 → 113 004, pic de places 10 → 6 ; saturation sur 4 semaines : capacité
    431 → 432 patients, pic de places 15 / 20 ; la ressource limitante reste le temps opératoire. Scénarios du SMA :
    cohérence OK partout.
  - tests ajoutés dans `test_occupation.py` : une place sert le matin puis l'après-midi après remise en état ; deux
    patients sur une place la même demi-journée sont refusés ; même décompte par demi-journée au niveau 2 et dans le
    SMA.

---

## Vérification finale

| Contrôle | Résultat |
|---|---|
| `python -m pytest interface/tests -m "not lent" -q` | 138 réussis (2 lents exclus) |
| `python -m pytest interface/tests -q` | 140 réussis |
| `grep` du lot 2 | aucune ligne |
| `python sma/scenarios_sma.py --liste` / `insertion_simple` | sans erreur |
| `python metaheuristiques/hybridation.py --help` | sans erreur |
| `python interface/tests/saturation.py --semaines 1` | sans erreur ; `interface/tests/resultats/` supprimé ensuite |
| `python -m streamlit run interface/app.py` | démarre ; Consultation, Planning, Urgences s'affichent sans erreur (régulation et chirurgien) ; Planning signale le programme enregistré non valide (lot 5) |
| `grep -rn "lits_disponibles_par_jour=\|temps_s=\|random_state=\|graine=[0-9]"` | plus aucune valeur littérale hors du fichier de paramètres : il reste des variables (`temps_s=P.budget_global_s`, `random_state=graine`) et `test_capacites.PETITE`, scénario de test |
| Fichiers de séjours individuels | aucun créé : seuls `donnees_hospitalieres.csv` (inchangé) et des métriques agrégées existent |

---

## Points à trancher par l'équipe

1. **Budget des campagnes** : 10 s est confirmé pour le site. Les campagnes utilisaient 20 s : les lancer avec
   `--temps 20`, ou garder 10 s ? Le budget est à indiquer dans le rapport.
2. **R1, pénalité de report pour W > 1** : sur un horizon de plusieurs semaines, la pénalité compte les semaines
   **après la fin de l'horizon** (`semaine_decalage`), pas le décalage depuis la semaine du patient. Fonction
   objectif non modifiée.
3. **Horaires des demi-journées** : avec 1 h de remise en état, une place est prête à 14 h, alors que les
   vacations de l'après-midi commencent à 13 h 30. Le premier patient ambulatoire de l'après-midi doit donc être
   accueilli ailleurs (ou la place du matin libérée à 12 h 30). La bascule à 13 h est réglable dans
   `commun/parametres.py`.
4. **Programme du site** : le recalculer (Administration → Lits et places → Recalculer) ; celui de la base date
   d'avant la correction des échanges et n'est pas valide.
5. **Scénarios du SMA** : leurs capacités passent à 30 / 3 / 20 (D4). Est-ce acceptable ?
6. **Transfert** : quand un plan interne existe, il est appliqué en attendant la décision du régulateur.
   Faut-il plutôt laisser l'urgence non programmée jusqu'à cette décision ?
7. **Sélection dans les recherches** : l'AGS et la recherche locale peuvent toujours garder en interne une
   solution non faisable comme meilleure (seule la sélection finale préfère les solutions faisables). Modifier
   cela touche les stratégies d'hybridation, hors périmètre.
8. **Capacités réelles** du site, **spécialités réelles** des chirurgiens et spécialités couvertes par l'équipe
   de garde (questions ouvertes de `CHOIX.md`).
