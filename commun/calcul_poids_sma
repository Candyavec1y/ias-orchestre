# -*- coding: utf-8 -*-
"""
sma/sma_sensibilite.py — Analyse de sensibilité des coefficients de coût du système multi-agents
================================================================================================

Reprend la méthode décrite en section « Fonction de coût du système multi-agents » :
  * chaque coefficient est multiplié par 0,5 puis par 2, UN SEUL À LA FOIS, sur l'ensemble des scénarios de
    scenarios_sma.py et avec les mêmes graines ;
  * trois indicateurs sont comparés au cas de référence :
        1. part des patients programmés dont l'affectation (salle, jour, chirurgien) est inchangée ;
        2. sort de chaque urgence (insérée / transférée) : nombre d'urgences dont le sort change ;
        3. nombre de patients perturbés = décalés (même jour) + reportés (autre jour) + en liste d'attente
           (déprogrammés non replacés) ;
  * une variation est SIGNIFICATIVE si elle dépasse celle observée entre deux exécutions identiques du cas de
    référence (« bruit »). En mode rapide (glouton, sans temps limite) le SMA est déterministe : le bruit est
    nul et toute variation de décision est significative ; en mode complet (Tabou local + optimisation globale,
    budgets en secondes) le bruit est mesuré.

Coefficients testés (ParametresSMA + poids d'attente des gravités) :
    c_decalage_min, c_avance_min, c_report_jour, c_deprogrammation, c_stabilite, c_retention_sspi_min,
    c_changement_chirurgien, c_astreinte, c_lit_reserve, c_lit_depassement,
    poids d'attente vitale / urgente / différable.
    Non testé : la pénalité « hors délai » (1e7), codée en dur dans sma_urgences.py (contrainte, pas un réglage).
    c_stabilite n'agit que si l'optimisation globale est active (--mode complet).

Sorties (resultats_sma_sensibilite/) :
    sensibilite_coefficients.png  un graphe par coefficient : écart des 3 indicateurs pour x0,5 et x2
    comparaison_coefficients.png  classement de l'influence + carte de chaleur coefficient x indicateur
    comparaison_valeurs.png       comparaison des coefficients entre eux (hiérarchie des perturbations)
    sensibilite_scenarios.png     carte de chaleur coefficient x scénario
    essais.csv, sensibilite.json, resume_latex.txt (phrase à reporter à la place du \\acompleter)

    python sma/sma_sensibilite.py                                  # rapide, 3 graines, tous les scénarios
    python sma/sma_sensibilite.py --mode complet --graines 2
    python sma/sma_sensibilite.py --scenarios fracture_panne journee_chargee --facteurs 0.5 2 4
    python sma/sma_sensibilite.py --poids-n2 resultats_poids_blocs/poids_optimaux.json
        (la référence prend alors c_lit_depassement = poids « lit » retenu par calibrer_poids_blocs.py,
         comme l'impose le commentaire de ParametresSMA : même valeur que PoidsNiveau2.lit)
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import sys
import time
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
_RACINE = Path(__file__).resolve().parents[1]
for _dossier in (_RACINE / "planning_vacations", _RACINE / "metaheuristiques",_RACINE / "sma"):
    if _dossier.is_dir() and str(_dossier) not in sys.path:
        sys.path.append(str(_dossier))
try:
    _DOSSIER = Path(__file__).resolve().parent
except NameError:
    _DOSSIER = Path.cwd()
sys.path.insert(0, str(_DOSSIER))

import scenarios_sma as SC          # noqa: E402  (ajoute planning_vacations/, metaheuristiques/, commun/ au chemin)
import sma_urgences as S            # noqa: E402
from parametres import GRAINE_SCENARIOS_SMA  # noqa: E402

# --------------------------------------------------------------------------------------------------------------
# 0. Robustesse : plans périmés
# --------------------------------------------------------------------------------------------------------------
# Lors d'une panne, sur_transferts_bloques applique à la suite plusieurs plans d'une même salle ; après un replacement,
# un plan calculé avant peut citer un patient déjà déplacé (KeyError sur salle.interventions[pid] dans _valider).
# Un tel plan est simplement rejeté (il est obsolète) ; le nombre de rejets est compté et affiché.
_OBSOLETES = [0]
_valider_origine = S.AgentRegulation._valider


def _valider_robuste(self, plan, conv):
    try:
        return _valider_origine(self, plan, conv)
    except KeyError as e:
        _OBSOLETES[0] += 1
        return False, 0.0, f"plan obsolète (patient {e} déjà déplacé)"


S.AgentRegulation._valider = _valider_robuste


# --------------------------------------------------------------------------------------------------------------
# 1. Coefficients testés : (clé, libellé, nature)
# --------------------------------------------------------------------------------------------------------------
COEFFICIENTS = [
    ("c_decalage_min", "retard / min (x p)", "patient"),
    ("c_avance_min", "avance / min (x p)", "patient"),
    ("c_report_jour", "report / jour (x p)", "patient"),
    ("c_deprogrammation", "déprogrammation (x p)", "patient"),
    ("c_stabilite", "stabilité (réopt. globale)", "stabilité"),
    ("c_retention_sspi_min", "rétention SSPI / min", "logistique"),
    ("c_changement_chirurgien", "reprise autre chirurgien", "ressources"),
    ("c_astreinte", "chirurgien d'astreinte", "ressources"),
    ("c_lit_reserve", "lit de réserve", "capacité"),
    ("c_lit_depassement", "lit hors capacité", "capacité"),
    ("attente:vitale", "attente vitale / min", "urgence"),
    ("attente:urgente", "attente urgente / min", "urgence"),
    ("attente:differable", "attente différable / min", "urgence"),
]
LIBELLE = {k: l for k, l, _ in COEFFICIENTS}
NATURE = {k: n for k, _, n in COEFFICIENTS}
MODES = {"rapide": dict(methode_locale=None, optimisation_globale=None), "complet": {}}
ALEATOIRES = ("semaine_normale", "semaine_surcharge")      # seuls scénarios qui dépendent de la graine
INDIC = [("modifiees", "affectations modifiées"), ("urgences", "urgences au sort changé"),
         ("perturbes", "patients perturbés")]
COULEURS = {"modifiees": "#2a78d6", "urgences": "#d62728", "perturbes": "#eda100"}


def valeur_base(cle: str, base_p: S.ParametresSMA) -> float:
    if cle.startswith("attente:"):
        return float(S.GRAVITES[cle.split(":")[1]].poids_attente)
    return float(getattr(base_p, cle))


# --------------------------------------------------------------------------------------------------------------
# 2. Une exécution = (configuration, scénario, graine)
# --------------------------------------------------------------------------------------------------------------
_ETAT: dict = {}


def resume(m: S.BlocOperatoire) -> dict:
    its = m.interventions()
    aff = {it.pid: (it.salle_id, it.debut.date().isoformat(), it.chirurgien_id) for it in its if not it.urgence}
    for it, _ in m.regulation.liste_attente:
        aff[it.pid] = ("attente",)
    dec = m.regulation.decisions
    ok = {d["patient"] for d in dec if d["type"] == "urgence"}
    tr = {d["patient"] for d in dec if d["type"] == "urgence_transferee"}
    sorts = {pid: "transferee" if pid in tr else "inseree" if pid in ok else "non_programmee"
             for pid in m.urgences_recues}
    b = m.bilan()
    return {"aff": aff, "sorts": sorts, "decales": b["patients_decales"], "reportes": b["patients_reportes_autre_jour"],
            "attente": b["patients_en_liste_attente"], "confrere": b["patients_repris_par_un_confrere"],
            "dans_delai": b["urgences_dans_delai"], "hors_delai": b["urgences_hors_delai"],
            "attente_moy_min": b["attente_moyenne_urgence_min"], "score": m.score_programme()["total"],
            "erreurs": b["erreurs_de_coherence"], "obsoletes": _OBSOLETES[0]}


def _jouer(tache):
    try:
        return _jouer_brut(tache)
    except Exception as e:                                  # une simulation en échec ne doit pas arrêter toute l'analyse
        import traceback
        cle, nom, graine = tache[0], tache[1], tache[2]
        fin = " | ".join(l.strip() for l in traceback.format_exc().strip().splitlines()[-6:])
        return cle, nom, graine, {"erreur": f"{type(e).__name__}: {e}  [{fin}]"}


def _jouer_brut(tache):
    cle, nom, graine, surcharges, gravites, mode = tache
    _OBSOLETES[0] = 0
    if "inst" not in _ETAT:
        _ETAT["inst"] = SC.instances_par_defaut()
        _ETAT["grav0"] = dict(S.GRAVITES)
    S.GRAVITES.clear()
    S.GRAVITES.update(_ETAT["grav0"])                    # remise à zéro avant chaque essai
    for g, v in gravites.items():
        S.GRAVITES[g] = replace(S.GRAVITES[g], poids_attente=v)
    P = S.ParametresSMA(**{**MODES[mode], **surcharges})
    if graine is not None:
        SC.GRAINE[0] = graine
    i1, i2, sol = _ETAT["inst"]
    sc = SC.SCENARIOS[nom]
    # Le Triage propose comme compétents tous les praticiens de specialites_par_id(), y compris ceux sans vacation sur
    # l'horizon : ils n'ont pas d'agent Chirurgien (KeyError « chir_7 »). On ne garde que les chirurgiens du modèle.
    spe = {c: s for c, s in S.specialites_par_id().items() if c in i1.chirurgiens}
    m = S.BlocOperatoire.depuis_v28(SC.LUNDI, instances=(i1, i2), solution=sol, verbeux=0, parametres=P,
                                    specialites=spe)
    evts = sc.evenements()
    for evt in evts:                                      # praticien d'une urgence absent du planning : agent sans présence
        p = getattr(evt, "patient", None)
        if p is not None and f"chir_{p.chirurgien_id}" not in m.annuaire:
            m.chirurgiens[p.chirurgien_id] = S.AgentChirurgien(m, p.chirurgien_id, f"chir {p.chirurgien_id}", set())
    for evt in evts:
        m.planifier(evt)
    m.executer_jusqu_a(sc.fin)
    return cle, nom, graine, resume(m)


def configuration(cle: str, facteur: float, base_p: S.ParametresSMA, base_sur: dict):
    """(surcharges ParametresSMA, poids d'attente des gravités) de l'essai « cle x facteur »."""
    sur, grav = dict(base_sur), {}
    if cle.startswith("attente:"):
        g = cle.split(":")[1]
        grav[g] = float(S.GRAVITES[g].poids_attente) * facteur
    elif cle != "ref":
        sur[cle] = valeur_base(cle, base_p) * facteur
    return sur, grav


# --------------------------------------------------------------------------------------------------------------
# 3. Indicateurs comparés à la référence
# --------------------------------------------------------------------------------------------------------------
def comparer(ref: dict, run: dict) -> dict:
    n = len(ref["aff"])
    same = sum(1 for p, v in ref["aff"].items() if run["aff"].get(p) == v)
    flips = sum(1 for p, f in ref["sorts"].items() if run["sorts"].get(p) != f)
    perturbes = run["decales"] + run["reportes"] + run["attente"]
    return {"n": n, "same": same, "flips": flips, "perturbes": perturbes,
            "perturbes_ref": ref["decales"] + ref["reportes"] + ref["attente"],
            "decales": run["decales"], "reportes": run["reportes"], "attente": run["attente"]}


def agreger(sous: dict, ref: dict) -> dict:
    """Somme sur tous les (scénario, graine) d'une configuration (`sous` : {(scénario, graine): résumé}) comparée à la référence."""
    tot = {"n": 0, "same": 0, "flips": 0, "perturbes": 0, "perturbes_ref": 0, "decales": 0, "reportes": 0,
           "attente": 0, "score": 0.0}
    par_sc: dict = {}
    for (nom, g), r in sous.items():
        c = comparer(ref[(nom, g)], r)
        for f in tot:
            if f in c:
                tot[f] += c[f]
        tot["score"] += r["score"]
        p = par_sc.setdefault(nom, {"n": 0, "same": 0, "flips": 0})
        for f in p:
            p[f] += c[f]
    tot["par_scenario"] = par_sc
    return tot


def ecarts(a: dict) -> dict:
    return {"modifiees": 100.0 * (1 - a["same"] / a["n"]) if a["n"] else 0.0,
            "urgences": float(a["flips"]),
            "perturbes": float(a["perturbes"] - a["perturbes_ref"])}


# --------------------------------------------------------------------------------------------------------------
# 4. Figures
# --------------------------------------------------------------------------------------------------------------
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def fig_sensibilite(res, facteurs, sortie: Path):
    plt = _plt()
    n = len(res["coefficients"])
    nc = 4
    nl = int(np.ceil(n / nc))
    fig, axes = plt.subplots(nl, nc, figsize=(3.6 * nc, 2.9 * nl), squeeze=False)
    largeur = 0.8 / len(INDIC)
    for ax in axes.flat[n:]:
        ax.axis("off")
    lim = max([1.0] + [abs(e["ratio"]) for d in res["coefficients"].values() for fe in d["essais"].values()
                       for e in fe.values()])
    lim = 10 ** np.ceil(np.log10(lim * 1.3))
    ticks = [t for t in (-1000, -100, -10, -1, 0, 1, 10, 100, 1000) if abs(t) <= lim]
    for ax, (cle, d) in zip(axes.flat, res["coefficients"].items()):
        for j, (ind, lib) in enumerate(INDIC):
            for i, f in enumerate(facteurs):
                e = d["essais"][str(f)][ind]
                x = i + (j - (len(INDIC) - 1) / 2) * largeur
                ax.bar(x, e["ratio"], largeur * 0.92, color=COULEURS[ind], alpha=1.0 if e["significatif"] else 0.28,
                       edgecolor=COULEURS[ind], lw=1)
        ax.axhline(1, color="grey", ls=":", lw=1)
        ax.axhline(-1, color="grey", ls=":", lw=1)
        ax.axhline(0, color="black", lw=0.6)
        ax.set_yscale("symlog", linthresh=1)
        ax.set_ylim(-lim, lim)
        ax.set_yticks(ticks, [str(t) for t in ticks], fontsize=7)
        ax.set_xticks(range(len(facteurs)), [f"x{f:g}\n({d['valeur'] * f:g})" for f in facteurs], fontsize=8)
        ax.set_title(f"{LIBELLE[cle]}  [base {d['valeur']:g}]", fontsize=8.5)
        ax.grid(axis="y", alpha=0.25)
        if d["decisif"]:
            ax.set_facecolor("#fff8e6")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COULEURS[i]) for i, _ in INDIC]
    fig.legend(handles, [lib for _, lib in INDIC], loc="lower center", ncol=3, fontsize=9, frameon=False)
    fig.suptitle("Sensibilité de chaque coefficient — écart à la référence, en multiples du seuil "
                 "(bruit ou 1 unité ; trait pointillé = seuil)\nbarre pleine : variation significative ; "
                 "barre pâle : dans le bruit ; fond crème : coefficient qui change les décisions",
                 x=0.01, ha="left", fontsize=10)
    fig.tight_layout(rect=(0, 0.04, 1, 0.92))
    fig.savefig(sortie / "sensibilite_coefficients.png", dpi=150, facecolor="white")
    plt.close(fig)


def fig_comparaison(res, facteurs, sortie: Path):
    plt = _plt()
    cles = sorted(res["coefficients"], key=lambda c: -res["coefficients"][c]["influence"])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 0.42 * len(cles) + 2.2),
                                 gridspec_kw={"width_ratios": [1, 1.5]})
    infl = [res["coefficients"][c]["influence"] for c in cles]
    a1.barh(range(len(cles)), infl, color=["#d97706" if res["coefficients"][c]["decisif"] else "#9ca3af" for c in cles])
    for i, v in enumerate(infl):
        a1.text(v, i, f" {v:.1f}", va="center", fontsize=8)
    a1.set_yticks(range(len(cles)), [LIBELLE[c] for c in cles], fontsize=9)
    a1.invert_yaxis()
    a1.axvline(1, color="grey", ls=":", lw=1)
    a1.set_xlabel("influence = plus grand écart (en multiples du seuil)")
    a1.set_title("Classement des coefficients\n(orange : change les décisions ; gris : sans effet)", fontsize=10)
    colonnes = [(ind, f) for ind, _ in INDIC for f in facteurs]
    M = np.array([[res["coefficients"][c]["essais"][str(f)][ind]["ratio"] for ind, f in colonnes] for c in cles])
    brut = [[res["coefficients"][c]["essais"][str(f)][ind]["ecart"] for ind, f in colonnes] for c in cles]
    im = a2.imshow(np.sign(M) * np.log10(1 + np.abs(M)), cmap="RdBu_r", aspect="auto", vmin=-2, vmax=2)
    for i in range(len(cles)):
        for j in range(len(colonnes)):
            a2.text(j, i, f"{brut[i][j]:+.1f}" if colonnes[j][0] == "perturbes" else f"{brut[i][j]:.1f}",
                    ha="center", va="center", fontsize=7.5,
                    fontweight="bold" if res["coefficients"][cles[i]]["essais"][str(colonnes[j][1])][colonnes[j][0]]
                    ["significatif"] else "normal")
    a2.set_xticks(range(len(colonnes)), [f"{dict(INDIC)[ind].split()[0]}\nx{f:g}" for ind, f in colonnes], fontsize=8)
    a2.set_yticks(range(len(cles)), [""] * len(cles))
    a2.set_title("Écart brut à la référence (gras : significatif)\naffectations modifiées en %, urgences en nombre, "
                 "patients perturbés en écart signé", fontsize=10)
    fig.colorbar(im, ax=a2, fraction=0.025, label="écart / seuil (échelle log signée)")
    fig.tight_layout()
    fig.savefig(sortie / "comparaison_coefficients.png", dpi=150, facecolor="white")
    plt.close(fig)


def fig_valeurs(base_p: S.ParametresSMA, w_lit: float, sortie: Path) -> dict:
    """Comparaison des coefficients ENTRE EUX : coût d'une unité et coût d'une perturbation type, priorité p = 1..4."""
    plt = _plt()
    P = base_p
    # (libellé, coût pour p=1, coût pour p=4, famille)
    unite = [("retard 1 min", P.c_decalage_min, 4 * P.c_decalage_min, "patient"),
             ("avance 1 min", P.c_avance_min, 4 * P.c_avance_min, "patient"),
             ("report 1 jour", P.c_report_jour, 4 * P.c_report_jour, "patient"),
             ("déprogrammation", P.c_deprogrammation, 4 * P.c_deprogrammation, "patient"),
             ("patient déplacé (réopt.)", P.c_stabilite, P.c_stabilite, "stabilité"),
             ("rétention SSPI 1 min", P.c_retention_sspi_min, P.c_retention_sspi_min, "logistique"),
             ("reprise autre chirurgien", P.c_changement_chirurgien, P.c_changement_chirurgien, "ressources"),
             ("chirurgien d'astreinte", P.c_astreinte, P.c_astreinte, "ressources"),
             ("lit de réserve", P.c_lit_reserve, P.c_lit_reserve, "capacité"),
             ("lit hors capacité", P.c_lit_depassement, P.c_lit_depassement, "capacité"),
             ("attente vitale 1 min", S.GRAVITES["vitale"].poids_attente, S.GRAVITES["vitale"].poids_attente, "urgence"),
             ("attente urgente 1 min", S.GRAVITES["urgente"].poids_attente, S.GRAVITES["urgente"].poids_attente, "urgence"),
             ("attente différable 1 min", S.GRAVITES["differable"].poids_attente,
              S.GRAVITES["differable"].poids_attente, "urgence")]
    type_ = [("retard 1 h", 60 * P.c_decalage_min, 4 * 60 * P.c_decalage_min, "patient"),
             ("avance 1 h", 60 * P.c_avance_min, 4 * 60 * P.c_avance_min, "patient"),
             ("report 2 jours", 2 * P.c_report_jour, 8 * P.c_report_jour, "patient"),
             ("déprogrammation", P.c_deprogrammation, 4 * P.c_deprogrammation, "patient"),
             ("rétention SSPI 1 h", 60 * P.c_retention_sspi_min, 60 * P.c_retention_sspi_min, "logistique"),
             ("reprise autre chirurgien", P.c_changement_chirurgien, P.c_changement_chirurgien, "ressources"),
             ("chirurgien d'astreinte", P.c_astreinte, P.c_astreinte, "ressources"),
             ("lit de réserve", P.c_lit_reserve, P.c_lit_reserve, "capacité"),
             ("lit hors capacité", P.c_lit_depassement, P.c_lit_depassement, "capacité")]
    coul = {"patient": "#2a78d6", "stabilité": "#6b7280", "logistique": "#10a37f", "ressources": "#8b5cf6",
            "capacité": "#d62728", "urgence": "#eda100"}
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.4))
    for ax, lignes, titre in ((axes[0], unite, "Coût d'une UNITÉ de perturbation"),
                              (axes[1], type_, "Coût d'une perturbation TYPE")):
        lignes = sorted(lignes, key=lambda x: x[1])
        for i, (lib, lo, hi, fam) in enumerate(lignes):
            ax.barh(i, lo, color=coul[fam], height=0.62)
            if hi > lo:
                ax.barh(i, hi - lo, left=lo, color=coul[fam], alpha=0.3, height=0.62, hatch="//")
            ax.text(hi * 1.12, i, f"{lo:g}" + (f" → {hi:g}" if hi > lo else ""), va="center", fontsize=8)
        ax.set_yticks(range(len(lignes)), [x[0] for x in lignes], fontsize=9)
        ax.set_xscale("log")
        ax.set_xlim(0.3, max(x[2] for x in lignes) * 6)
        ax.set_title(titre + "  (hachuré : de p = 1 à p = 4)", fontsize=10)
        ax.grid(axis="x", alpha=0.25)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in coul.values()]
    fig.legend(handles, list(coul), loc="lower center", ncol=len(coul), frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(sortie / "comparaison_valeurs.png", dpi=150, facecolor="white")
    plt.close(fig)
    # hiérarchie annoncée : décaler < (lit de réserve, chirurgien) < astreinte < déprogrammation < lit hors capacité
    ordre = [("décaler 1 h (p max)", 4 * 60 * P.c_decalage_min), ("lit de réserve", P.c_lit_reserve),
             ("changer de chirurgien", P.c_changement_chirurgien), ("astreinte", P.c_astreinte),
             ("déprogrammer (p = 1)", P.c_deprogrammation), ("lit hors capacité", P.c_lit_depassement)]
    verifs = [(a[0], b[0], a[1] <= b[1]) for a, b in zip(ordre, ordre[1:])]
    p_exception = [p for p in (1, 2, 3, 4) if P.c_deprogrammation * p > P.c_lit_depassement]
    return {"hierarchie": [{"de": a, "a": b, "respectee": ok} for a, b, ok in verifs],
            "priorites_ou_deprogrammer_coute_plus_qu_un_lit": p_exception,
            "ecart_c_lit_depassement_vs_poids_n2_lit": P.c_lit_depassement - w_lit}


def fig_scenarios(res, scenarios, sortie: Path):
    plt = _plt()
    cles = sorted(res["coefficients"], key=lambda c: -res["coefficients"][c]["influence"])
    M = np.array([[res["coefficients"][c]["par_scenario"].get(s, 0.0) for s in scenarios] for c in cles])
    fig, ax = plt.subplots(figsize=(1.0 * len(scenarios) + 4, 0.42 * len(cles) + 2))
    im = ax.imshow(M, cmap="YlOrRd", aspect="auto", vmin=0)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if M[i, j] > 0:
                ax.text(j, i, f"{M[i, j]:.1f}", ha="center", va="center", fontsize=7.5)
    ax.set_xticks(range(len(scenarios)), scenarios, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(cles)), [LIBELLE[c] for c in cles], fontsize=9)
    ax.set_title("Affectations modifiées (%) par scénario — plus grand écart sur les facteurs testés", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.03, label="% de patients dont l'affectation change")
    fig.tight_layout()
    fig.savefig(sortie / "sensibilite_scenarios.png", dpi=150, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------------------------------------------
# 5. Programme principal
# --------------------------------------------------------------------------------------------------------------
def main():
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description="Sensibilité des coefficients de coût du SMA")
    ap.add_argument("--mode", choices=list(MODES), default="rapide",
                    help="rapide : glouton déterministe ; complet : Tabou local + optimisation globale (budgets)")
    ap.add_argument("--facteurs", type=float, nargs="+", default=[0.5, 2.0])
    ap.add_argument("--graines", type=int, default=3, help="graines des scénarios aléatoires")
    ap.add_argument("--scenarios", nargs="+", default=list(SC.SCENARIOS), choices=list(SC.SCENARIOS))
    ap.add_argument("--coefficients", nargs="+", default=[c for c, _, _ in COEFFICIENTS],
                    choices=[c for c, _, _ in COEFFICIENTS])
    ap.add_argument("--poids-n2", default=None, help="poids_optimaux.json de calibrer_poids_blocs.py")
    ap.add_argument("--coeurs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--sortie", default="resultats_sma_sensibilite")
    o, _ = ap.parse_known_args()
    sortie = Path(o.sortie)
    sortie.mkdir(parents=True, exist_ok=True)

    # --- référence : paramètres du dépôt, éventuellement alignés sur les poids N2 calibrés
    base_sur = dict(MODES[o.mode])
    w_lit = float(S.POIDS_N2.lit)
    if o.poids_n2:
        w_lit = float(json.loads(Path(o.poids_n2).read_text(encoding="utf-8"))["poids_retenus"]["lit"])
        base_sur["c_lit_depassement"] = w_lit
        print(f"  c_lit_depassement aligné sur le poids N2 « lit » retenu : {w_lit:g}")
    base_p = S.ParametresSMA(**base_sur)

    graines = [GRAINE_SCENARIOS_SMA + k for k in range(max(1, o.graines))]
    runs_def = [(nom, g) for nom in o.scenarios for g in (graines if nom in ALEATOIRES else [None])]
    configs = [("ref", 1.0), ("ref2", 1.0)] + [(c, f) for c in o.coefficients for f in o.facteurs]
    taches = []
    for cle, f in configs:
        sur, grav = configuration("ref" if cle == "ref2" else cle, f, base_p, base_sur)
        for nom, g in runs_def:
            taches.append(((cle, f), nom, g, sur, grav, o.mode))
    print(f"{len(configs)} configurations x {len(runs_def)} scénario(s)/graine(s) = {len(taches)} simulations "
          f"(mode {o.mode}, {o.coeurs} cœur(s))")
    t0 = time.perf_counter()
    _ETAT["inst"] = SC.instances_par_defaut()          # construites une fois, héritées par les processus (fork)
    _ETAT["grav0"] = dict(S.GRAVITES)
    brut = []
    if o.coeurs > 1:
        with mp.Pool(o.coeurs) as pool:
            for i, r in enumerate(pool.imap_unordered(_jouer, taches), 1):
                brut.append(r)
                if i % 25 == 0:
                    print(f"  {i}/{len(taches)} ({time.perf_counter() - t0:.0f} s)")
    else:
        for i, t in enumerate(taches, 1):
            brut.append(_jouer(t))
            if i % 25 == 0:
                print(f"  {i}/{len(taches)} ({time.perf_counter() - t0:.0f} s)")
    S.GRAVITES.clear()
    S.GRAVITES.update(_ETAT["grav0"])                    # (mode 1 cœur : les essais ont modifié GRAVITES)
    runs = {(cf, nom, g): r for (cf, nom, g, r) in brut}
    echecs = {}
    for (cf, nom, g), r in runs.items():
        if "erreur" in r:
            echecs.setdefault((nom, g), (cf, r["erreur"]))
    if echecs:
        print(f"\n  {len(echecs)} scénario(s) écarté(s) car au moins une simulation a échoué :")
        for (nom, g), (cf, err) in echecs.items():
            print(f"   - {nom} (graine {g}), config {cf} : {err}")
        runs = {k: r for k, r in runs.items() if (k[1], k[2]) not in echecs}
        if not any(k[0] == ("ref", 1.0) for k in runs):
            sys.exit("Aucune simulation de référence n'a abouti : voir les erreurs ci-dessus.")
        (sortie / "scenarios_en_echec.txt").write_text("\n".join(f"{n} {g} {c} {e}" for (n, g), (c, e) in
                                                              echecs.items()), encoding="utf-8")
    ref = {(nom, g): r for (cf, nom, g), r in runs.items() if cf == ("ref", 1.0)}
    obs = sum(r["obsoletes"] for r in runs.values())
    if obs:
        print(f"  {obs} plan(s) périmé(s) rejeté(s) pendant les pannes (voir le correctif de sur_transferts_bloques)")
    erreurs = sum(r["erreurs"] for r in runs.values())
    if erreurs:
        print(f"  ATTENTION : {erreurs} erreur(s) de cohérence détectée(s) dans les simulations")

    # --- bruit = écart entre deux exécutions identiques de la référence
    a_ref2 = agreger({(nom, g): r for (cf, nom, g), r in runs.items() if cf == ("ref2", 1.0)}, ref)
    bruit = ecarts(a_ref2)
    bruit["perturbes"] = abs(bruit["perturbes"])

    total_n = sum(len(r["aff"]) for r in ref.values())
    unite = {"modifiees": 100.0 / max(1, total_n), "urgences": 1.0, "perturbes": 1.0}
    resultat = {"mode": o.mode, "facteurs": o.facteurs, "bruit": bruit, "coefficients": {}, "scenarios": o.scenarios,
                "graines": graines}
    lignes = []
    for cle in o.coefficients:
        d = {"valeur": valeur_base(cle, base_p), "essais": {}, "par_scenario": {}}
        for f in o.facteurs:
            a = agreger({(nom, g): r for (cf, nom, g), r in runs.items() if cf == (cle, f)}, ref)
            e = ecarts(a)
            d["essais"][str(f)] = {}
            for ind, _ in INDIC:
                ecart = abs(e[ind])
                seuil = max(bruit[ind], unite[ind])
                signe = -1 if (ind == "perturbes" and e[ind] < 0) else 1
                d["essais"][str(f)][ind] = {"ecart": e[ind], "ratio": signe * ecart / seuil,
                                            "significatif": bool(ecart > bruit[ind] and ecart > 0)}
            for nom, p in a["par_scenario"].items():
                pc = 100.0 * (1 - p["same"] / p["n"]) if p["n"] else 0.0
                d["par_scenario"][nom] = max(d["par_scenario"].get(nom, 0.0), pc)
            lignes.append({"coefficient": cle, "facteur": f, "valeur": d["valeur"] * f, **{
                f"ecart_{i}": e[i] for i, _ in INDIC}, "part_inchangee_pct": 100 * a["same"] / a["n"],
                "decales": a["decales"], "reportes": a["reportes"], "en_attente": a["attente"],
                "score_total": a["score"]})
        d["influence"] = max(abs(v["ratio"]) for fe in d["essais"].values() for v in fe.values())
        d["decisif"] = any(v["significatif"] for fe in d["essais"].values() for v in fe.values())
        d["sort_urgences_change"] = any(fe["urgences"]["significatif"] for fe in d["essais"].values())
        resultat["coefficients"][cle] = d

    with (sortie / "essais.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lignes[0]), delimiter=";")
        w.writeheader()
        w.writerows(lignes)

    # --- figures
    try:
        fig_sensibilite(resultat, o.facteurs, sortie)
        fig_comparaison(resultat, o.facteurs, sortie)
        resultat["comparaison_valeurs"] = fig_valeurs(base_p, w_lit, sortie)
        fig_scenarios(resultat, o.scenarios, sortie)
    except ImportError:
        print("  (matplotlib absent : figures ignorées)")

    decisifs = [c for c in o.coefficients if resultat["coefficients"][c]["decisif"]]
    sans = [c for c in o.coefficients if not resultat["coefficients"][c]["decisif"]]
    resultat["decisifs"], resultat["sans_effet"] = decisifs, sans
    (sortie / "sensibilite.json").write_text(json.dumps(resultat, ensure_ascii=False, indent=2, default=float),
                                             encoding="utf-8")
    lib = lambda cs: ", ".join(LIBELLE[c] for c in cs) or "aucun"          # noqa: E731
    tex = (f"Sur {len(runs_def)} exécutions de scénarios ({len(o.scenarios)} scénarios, {len(graines)} graines pour les "
           f"scénarios aléatoires), les coefficients qui modifient les décisions du système sont : {lib(decisifs)}. "
           f"Les coefficients suivants n'ont pas d'effet significatif : {lib(sans)}. "
           f"Seuil de significativité : variation entre deux exécutions identiques de la référence "
           f"({bruit['modifiees']:.2f} \\% d'affectations, {bruit['urgences']:.0f} urgence(s), "
           f"{bruit['perturbes']:.0f} patient(s) perturbé(s)).")
    (sortie / "resume_latex.txt").write_text(tex, encoding="utf-8")

    print(f"\n  Bruit (2 exécutions identiques) : {bruit}")
    print("  Coefficients qui changent les décisions :", lib(decisifs))
    print("  Coefficients sans effet significatif    :", lib(sans))
    hier = resultat.get("comparaison_valeurs", {})
    for h in hier.get("hierarchie", []):
        print(f"  hiérarchie {h['de']} <= {h['a']} : {'OK' if h['respectee'] else 'NON RESPECTÉE'}")
    if hier.get("priorites_ou_deprogrammer_coute_plus_qu_un_lit"):
        print("  exception : déprogrammer coûte plus qu'un lit en trop pour p =",
              hier["priorites_ou_deprogrammer_coute_plus_qu_un_lit"])
    print(f"  {sortie}/ ({time.perf_counter() - t0:.0f} s)")


if __name__ == "__main__":
    mp.freeze_support()
    main()