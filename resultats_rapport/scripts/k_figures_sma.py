# -*- coding: utf-8 -*-
"""Figure F11 (stratégies SMA : urgences dans le délai contre perturbations) et compléments du manifeste."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from commun_rapport import SORTIE, enregistrer_manifeste, lire_csv, sauver_figure  # noqa: E402

SCRIPT = "scripts/k_figures_sma.py"
STRAT = ["S_CN", "S_LOC", "S_GLOB", "S_LOC_GLOB"]


def main():
    lignes = [l_ for l_ in lire_csv(SORTIE / "sma_scenarios.csv") if not l_.get("echec") and not l_["graine"]]
    somme = {s: {k: sum(float(l_[k] or 0) for l_ in lignes if l_["strategie"] == s)
                 for k in ("urgences_recues", "urgences_dans_delai", "decales", "reportes_autre_jour",
                           "liste_attente", "repris_confrere", "temps_simulation_reel_s")} for s in STRAT}
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), layout="constrained")
    x = np.arange(len(STRAT))
    for i, (k, nom) in enumerate((("urgences_dans_delai", "urgences dans le délai"), ("decales", "patients décalés"),
                                  ("reportes_autre_jour", "reportés à un autre jour"), ("liste_attente", "en liste d'attente"))):
        axes[0].bar(x + (i - 1.5) * 0.2, [somme[s][k] for s in STRAT], 0.2, label=nom,
                    color=["0.1", "0.4", "0.65", "0.9"][i], edgecolor="k")
    axes[0].set_xticks(x, STRAT)
    axes[0].set(ylabel="Total sur 21 scénarios déterministes",
                title=f"Urgences ({int(somme['S_CN']['urgences_recues'])} reçues) et perturbations du programme")
    axes[0].legend(fontsize=8)
    axes[1].bar(x, [somme[s]["temps_simulation_reel_s"] for s in STRAT], color="0.5", edgecolor="k")
    axes[1].set_xticks(x, STRAT)
    axes[1].set(ylabel="Temps réel de calcul cumulé (s)", title="Coût de calcul de la régulation")
    fig.suptitle("SMA : stratégies comparées à événements identiques (programme figé et régulation simple : non disponibles)")
    figs = sauver_figure(fig, "sma_strategies")
    plt.close(fig)
    enregistrer_manifeste("F11 stratégies SMA", ["sma_scenarios.csv"], SCRIPT, note=", ".join(figs))
    enregistrer_manifeste("F9/F10 Gantt SMA avant / après", ["sma_scenarios.csv"], "scripts/h_sma.py",
                          note="figures/sma_gantt_urgence_panne_1310_*, sma_gantt_surcharge_1510_*, "
                               "sma_gantt_prolongation_1310_*, sma_gantt_lits_1310_* / _1410_* (PNG seulement)")
    for nom, statut, note in (
            ("F8 lits matin / soir", "NON DISPONIBLE", "pas d'heure d'admission dans le modèle ; remplacé par "
                                                        "figures/ressources_lits_rotation (sorties à midi, admissions du jour)"),
            ("Stratégies SMA programme figé / régulation simple", "NON DISPONIBLE", "voir QUESTIONS.md"),
            ("Gap d'optimalité", "NON DISPONIBLE", "aucune borne valide"),
            ("P2 (front non dominé, ablations, poids)", "NON EXÉCUTÉ (coût/temps)", "voir QUESTIONS.md"),
            ("Pilote", "NON UTILISÉ", "donnees_agregees/pilote/ : calibrage de la chaîne, hors résultats"),
            ("Textes", "CALCULÉ À PARTIR DE MESURES", "RESUME.md, INTERPRETATION.md, *_resume.md, parametres.md")):
        enregistrer_manifeste(nom, [], "—", statut=statut, note=note)
    print("F11 et manifeste complétés")


if __name__ == "__main__":
    main()
