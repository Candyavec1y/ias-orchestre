# -*- coding: utf-8 -*-
"""
Sensibilité des coefficients de coût du SMA : lance sma/sma_sensibilite.py (mode rapide, chaque coefficient × 0,5 puis
× 2, un seul à la fois, sur tous les scénarios de scenarios_sma.py et 3 graines) sans le modifier, puis trace :
  * sma_sensibilite_affectations : affectations (salle, jour, chirurgien) modifiées par rapport à la référence ;
  * sma_sensibilite_perturbes : variation du nombre de patients perturbés (décalés + reportés + en liste d'attente).
Seuls les coefficients qui changent au moins une décision sont affichés.
"""
from __future__ import annotations

import json
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from commun_rapport import AGREGEES, RACINE, sauver_figure  # noqa: E402

DOSSIER = AGREGEES / "sma_sensibilite"
LIBELLES = {"c_decalage_min": "Retard (/min)", "c_avance_min": "Avance (/min)", "c_report_jour": "Report (/jour)",
            "c_deprogrammation": "Déprogrammation", "c_stabilite": "Stabilité (réopt. globale)",
            "c_retention_sspi_min": "Rétention SSPI (/min)", "c_changement_chirurgien": "Reprise autre chirurgien",
            "c_astreinte": "Chirurgien d'astreinte", "c_lit_reserve": "Lit de réserve",
            "c_lit_depassement": "Lit hors capacité", "attente:vitale": "Attente vitale (/min)",
            "attente:urgente": "Attente urgente (/min)", "attente:differable": "Attente différable (/min)"}
CLAIR, FONCE = "#a1c6f7", "#1f5fbf"


def nombre_affectations_reference() -> int:
    """Nombre d'affectations comparées (somme sur les scénarios et graines de la référence), recalculé avec les
    fonctions de sma_sensibilite.py ; les scénarios écartés par l'étude (simulation en échec) ne sont pas comptés."""
    sys.path.insert(0, str(RACINE / "sma"))
    import sma_sensibilite as SS
    echecs = set()
    f = DOSSIER / "scenarios_en_echec.txt"
    if f.exists():
        for ligne in f.read_text(encoding="utf-8").splitlines():
            nom, g = ligne.split()[:2]
            echecs.add((nom, None if g == "None" else int(g)))
    graines = [SS.GRAINE_SCENARIOS_SMA + k for k in range(3)]
    total = 0
    for nom in SS.SC.SCENARIOS:
        for g in (graines if nom in SS.ALEATOIRES else [None]):
            if (nom, g) in echecs:
                continue
            sur, grav = SS.configuration("ref", 1.0, SS.S.ParametresSMA(**SS.MODES["rapide"]), dict(SS.MODES["rapide"]))
            r = SS._jouer(((("ref", 1.0)), nom, g, sur, grav, "rapide"))[3]
            if "erreur" not in r:
                total += len(r["aff"])
    return total


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(RACINE / "sma" / "sma_sensibilite.py"), "--mode", "rapide", "--graines", "3",
                    "--coeurs", "4", "--sortie", str(DOSSIER)], check=True, cwd=RACINE)
    res = json.loads((DOSSIER / "sensibilite.json").read_text(encoding="utf-8"))
    n = nombre_affectations_reference()
    lignes = []
    for cle, d in res["coefficients"].items():
        e05, e2 = d["essais"]["0.5"], d["essais"]["2.0"]
        lignes.append((cle, round(e05["modifiees"]["ecart"] * n / 100), round(e2["modifiees"]["ecart"] * n / 100),
                       int(round(e05["perturbes"]["ecart"])), int(round(e2["perturbes"]["ecart"]))))
    lignes = [l_ for l_ in lignes if any(l_[1:])]
    lignes.sort(key=lambda l_: max(l_[1], l_[2]), reverse=True)

    def barres(titre_x, i05, i2, nom, symetrique=False):
        fig, ax = plt.subplots(figsize=(7.5, 0.55 * len(lignes) + 1.2), layout="constrained")
        y = range(len(lignes))
        for k, (l_, h) in enumerate(((i05, -0.2), (i2, 0.2))):
            vals = [x[l_] for x in lignes]
            ax.barh([v + h for v in y], vals, 0.38, color=(CLAIR, FONCE)[k],
                    label=("coefficient × 0,5", "coefficient × 2")[k])
            for yy, v in zip(y, vals):
                if v:
                    txt = f"{v:+d}".replace("-", "−") if symetrique else f"{v}"
                    ax.text(v + (0.3 if v >= 0 else -0.3), yy + h, txt, va="center",
                            ha="left" if v >= 0 else "right", fontsize=9, color="0.25")
        ax.set_yticks(list(y), [LIBELLES.get(x[0], x[0]) for x in lignes])
        ax.invert_yaxis()
        ax.set_xlabel(titre_x)
        ax.grid(axis="x", color="0.9")
        ax.set_axisbelow(True)
        for c in ("top", "right"):
            ax.spines[c].set_visible(False)
        if symetrique:
            m = max(abs(x[i]) for x in lignes for i in (i05, i2)) + 2
            ax.set_xlim(-m, m)
            ax.axvline(0, color="0.3", lw=1)
        ax.legend(frameon=False, loc="lower right")
        sauver_figure(fig, nom)
        plt.close(fig)

    barres(f"Affectations modifiées par rapport à la référence (sur {n:,})".replace(",", " "), 1, 2,
           "sma_sensibilite_affectations")
    barres("Variation du nombre de patients perturbés", 3, 4, "sma_sensibilite_perturbes", symetrique=True)
    print(f"{len(lignes)} coefficients affichés, {n} affectations de référence")


if __name__ == "__main__":
    main()
