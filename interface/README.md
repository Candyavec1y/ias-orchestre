# OR'CHESTRE — interface web

Installation et lancement : voir le [README à la racine du dépôt](../README.md).

## Pages et briques du dépôt utilisées

| Page | Comptes | Brique du dépôt | Rôle |
|---|---|---|---|
| **Tableau de bord** | admin | — | lits et places occupés, occupation du bloc, état des salles, tendances, qualité de service |
| **Historique** | admin | — | journal horodaté, en ajout seul et scellé, de toutes les actions et des déplacements de patients |
| **Accueil** | chirurgien, cadre de bloc | `metaheuristiques/`, `sma/` | chirurgien : son planning et ses patients du jour ; cadre de bloc : programme de toutes les salles |
| **Consultation** | tous | `machine_learning/` (HistGradientBoosting) | saisie de la consultation, prédictions (prise en charge, durée, nuits), priorité proposée par la règle d'urgence (non validée cliniquement), validation par le médecin, choix du créneau |
| **Planning** | tous | `planning_vacations/planning_vacations_v28.py`, `metaheuristiques/hybridation.py` | vacations de la semaine, programme opératoire du jour (Gantt), occupation anonyme des salles, contraintes violées si le programme n'est pas valide (cadre de bloc, admin) |
| **Urgences** | tous | `sma/sma_urgences.py` (Mesa) | déclarer une urgence, une panne du monte-lit, la prolongation d'une intervention, des lits indisponibles (cadre de bloc, admin), une absence ; suivi des urgences et transferts proposés ; fil des décisions et messages entre agents (admin) |
| **Patients** | tous (chirurgien : ses patients) | — | statut, annulation, export et effacement (RGPD) |
| **Administration** | admin | — | comptes, planning des vacations, lits et places, optimisation globale, horloge de démonstration |
| **Confidentialité** | tous | — | notice d'information patient, mesures RGPD / CNIL |

## Organisation du code

* `app.py` : connexion, barre latérale et navigation selon le rôle.
* `vues/` : une page par fichier ; `commun.py` (charte graphique, session, historique), `graphiques.py` (Plotly).
* `orchestre/` : `ml.py` (prédictions), `programme.py` (métaheuristiques), `sma_service.py` (système
  multi-agent), `stockage.py` (SQLite, chiffrement, historique scellé), `chemins.py` (accès au dépôt),
  `libelles_codes.json` (libellés officiels CIM-10 / CCAM).
* `donnees/` : créé au premier lancement (base, clés, comptes de démonstration) ; **jamais versionné**.

## Tests

```bash
python -m pytest interface/tests -m "not lent"
```

Détail : [tests/README.md](tests/README.md).

Les choix de conception (et les questions ouvertes) sont détaillés dans [CHOIX.md](CHOIX.md).
