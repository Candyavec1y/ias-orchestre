# -*- coding: utf-8 -*-
"""
Branche v3 : réoptimisation globale du SMA avec trois méthodes (mémétique, RS seul, AGS>RS>TABOU), sans optimisation
locale (comme le site si on activait la globale), budget 1 s, sur les 21 scénarios déterministes de h_sma.py ;
référence : Contract Net sans métaheuristique (S_CN).
"""
from __future__ import annotations

import time

import h_sma
from commun_rapport import AGREGEES, ecrire_csv

h_sma.STRATEGIES.update({"G_memetique": dict(methode_locale=None, optimisation_globale="memetique"),
                         "G_RS": dict(methode_locale=None, optimisation_globale="RS seul"),
                         "G_AGS>RS>TABOU": dict(methode_locale=None, optimisation_globale="AGS>RS>TABOU")})
STRAT = ["S_CN", "G_memetique", "G_RS", "G_AGS>RS>TABOU"]


def main():
    noms = [n for n in h_sma.SC_SMA.SCENARIOS if n not in h_sma.ALEATOIRES]
    t0 = time.perf_counter()
    lignes = []
    for nom in noms:
        for s in STRAT:
            l_, _ = h_sma.jouer(nom, s)
            lignes.append({k: (str(v) if isinstance(v, dict) else v) for k, v in l_.items()})
    (AGREGEES / "v3_pilote").mkdir(parents=True, exist_ok=True)
    ecrire_csv(AGREGEES / "v3_pilote" / "sma_reoptimisation_globale.csv", lignes)
    print(f"{len(lignes)} exécutions en {time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    main()
