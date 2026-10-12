# OR'CHESTRE — interface d'aide à la décision du bloc opératoire

Interface web (Python / Streamlit) qui relie les briques du dépôt :

| Onglet | Brique du dépôt | Rôle |
|---|---|---|
| **Consultation** | `machine_learning/` (modèles HistGradientBoosting, validation 80/20) | saisir les données de consultation, obtenir capacité, durée de bloc, nuits pré/post-op, score d'urgence ; le chirurgien valide puis choisit un créneau proposé par le SMA |
| **Planning** | `planning_vacations/planning_vacations_v28.py`, `metaheuristiques/hybridage2.py`, `recuit_simulé.py` | planning fixe des vacations (parité des semaines), programme opératoire du jour (Gantt), calcul et comparaison des métaheuristiques / hybridations, niveau 1 |
| **Urgences** | `sma/sma_urgences.py` (Mesa) | déclarer urgences et pannes, suivre décisions, alertes et messages entre agents |
| **Patients** | — | statut des patients inscrits, annulation, export, effacement (RGPD) |
| **Administration** | — | comptes, horloge de démonstration, conservation, journal des accès, qualité du modèle |
| **Confidentialité** | — | notice d'information patient, mesures RGPD / CNIL |

## Démarrage

```bash
pip install -r interface/requirements.txt
streamlit run interface/app.py
```

Au premier lancement l'application :
1. crée `interface/donnees/` (base SQLite, clé de chiffrement, **comptes de démonstration** dans
   `comptes_demo.txt` — mot de passe à changer à la première connexion) ;
2. calcule le programme opératoire initial de la semaine en cours (hybridation mémétique, ~10 s).

Pour une démonstration : connectez-vous en `admin`, onglet Administration → Horloge, fixez par exemple
mardi 9 h 00, puis déclarez une urgence et une panne du monte-lit depuis l'onglet Urgences.

## Tests

```bash
python -m pytest interface/tests -q
```

Les choix de conception (et les questions ouvertes) sont détaillés dans [CHOIX.md](CHOIX.md).
