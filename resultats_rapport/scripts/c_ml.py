# -*- coding: utf-8 -*-
"""
Tâche C : machine learning. Protocole du projet (machine_learning/preparation.py) : préparation commune, séparation
UNIQUE 80/20 par SÉJOUR stratifiée sur le mode de prise en charge (GRAINE_ML), nuits avant / après sur les
hospitalisés. Les modèles évalués sont des copies réentraînées EN MÉMOIRE sur la partie entraînement (mêmes
hyperparamètres) ; les modèles déployés (.joblib, entraînés sur 100 % des séjours) ne sont ni modifiés ni réécrits.

Confidentialité : aucune ligne individuelle n'est exportée. L'identifiant patient n'est lu qu'en mémoire pour
compter les recouvrements entraînement / test ; les figures réel / prédit sont des cartes de densité (hexbin).
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from commun_rapport import AGREGEES, SORTIE, ecrire_csv, enregistrer_manifeste, sauver_figure

import preparation as PREP
from sklearn.metrics import brier_score_loss, mean_absolute_error, mean_squared_error, precision_recall_fscore_support, r2_score

SCRIPT = "scripts/c_ml.py"


def _reg(y, p, unite: str) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    e = p - y
    a = np.abs(e)
    return {"n_test": len(y), "unite": unite, "r2": r2_score(y, p), "mae": mean_absolute_error(y, p),
            "rmse": float(np.sqrt(mean_squared_error(y, p))), "erreur_abs_mediane": float(np.median(a)),
            "erreur_abs_p90": float(np.quantile(a, 0.9)), "erreur_abs_p95": float(np.quantile(a, 0.95)),
            "erreur_signee_moyenne": float(e.mean()), "part_sous_estimation_pct": float((e < 0).mean() * 100),
            "sous_estimation_moyenne": float(-e[e < 0].mean()) if (e < 0).any() else float("nan"),
            "part_erreur_le_1_pct": float((a <= 1).mean() * 100), "part_erreur_le_2_pct": float((a <= 2).mean() * 100)}


def main():
    t0 = time.perf_counter()
    brut = pd.read_csv(PREP.CSV_DONNEES, encoding="utf-8", on_bad_lines="skip", low_memory=False)
    n_brut = len(brut)
    df = PREP.charger_et_preparer()
    t_prep = time.perf_counter() - t0
    lignes = [{"modele": "donnees", "metrique": "sejours_bruts", "valeur": n_brut, "statut": "MESURÉ"},
              {"modele": "donnees", "metrique": "sejours_apres_preparation", "valeur": len(df), "statut": "MESURÉ"},
              {"modele": "donnees", "metrique": "sejours_exclus", "valeur": n_brut - len(df), "statut": "CALCULÉ"}]
    for c, n in df[PREP.CIBLE_CAPACITE].value_counts().items():
        lignes.append({"modele": "donnees", "metrique": f"effectif_{c}", "valeur": int(n), "statut": "MESURÉ"})

    # --- séparation : par séjour ; recouvrement de patients compté en mémoire, seuls les comptes sont exportés ---
    tr, te = PREP.separer(df)
    col_id = next((c for c in brut.columns if "id" in c.lower() and "patient" in c.lower()), None)
    col_cas = next((c for c in brut.columns if c.lower().replace(" ", "_") == "no_cas"), None)
    if col_id and col_cas and "no_cas" in df.columns:
        ident = dict(zip(brut[col_cas], brut[col_id]))
        p_tr, p_te = {ident.get(x) for x in tr["no_cas"]}, [ident.get(x) for x in te["no_cas"]]
        recouvre = sum(p in p_tr for p in p_te)
        lignes += [{"modele": "separation", "metrique": "patients_distincts", "valeur": len(set(ident.get(x) for x in df["no_cas"])), "statut": "MESURÉ"},
                   {"modele": "separation", "metrique": "sejours_test_dont_patient_en_entrainement", "valeur": recouvre, "statut": "MESURÉ"},
                   {"modele": "separation", "metrique": "part_sejours_test_patient_vu_pct", "valeur": 100 * recouvre / len(te), "statut": "CALCULÉ"}]
        del ident, p_tr, p_te
    del brut

    t1 = time.perf_counter()
    res, pred, pred_lit = PREP.evaluer(df, details=True)
    t_eval = time.perf_counter() - t1
    lignes += [{"modele": "separation", "metrique": k, "valeur": res[k], "statut": "MESURÉ"}
               for k in ("n_train", "n_test", "n_test_hospitalises")]

    # --- durée opératoire (heures et minutes) + références simples apprises sur l'ENTRAÎNEMENT ---
    yb, pb = pred["duree_bloc_heures"].values, pred["bloc_h_predit"].values
    ref_med = np.full_like(yb, tr["duree_bloc_heures"].median())
    med_type = tr.groupby("type_intervention")["duree_bloc_heures"].median()
    ref_type = pred["type_intervention"].map(med_type).fillna(tr["duree_bloc_heures"].median()).values
    blocs = {"duree_bloc_modele_h": _reg(yb, pb, "h"), "duree_bloc_modele_min": _reg(yb * 60, pb * 60, "min"),
             "duree_bloc_ref_mediane_min": _reg(yb * 60, ref_med * 60, "min"),
             "duree_bloc_ref_mediane_par_type_min": _reg(yb * 60, ref_type * 60, "min")}
    # --- nuits avant / après (hospitalisés du test) + référence médiane de l'entraînement hospitalisé ---
    lit_tr = tr[tr[PREP.CIBLE_CAPACITE] == PREP.HOSPITALISE]
    for cible, col, colp in (("nuits_avant", "duree_avant_operation", "avant_j_predit"),
                             ("nuits_apres", "duree_apres_operation", "apres_j_predit")):
        y = pred_lit[col].values
        blocs[f"{cible}_modele_j"] = _reg(y, pred_lit[colp].values, "nuit")
        blocs[f"{cible}_ref_mediane_j"] = _reg(y, np.full_like(y, lit_tr[col].median(), dtype=float), "nuit")
    for nom, d in blocs.items():
        for k, v in d.items():
            if k != "unite":
                lignes.append({"modele": nom, "metrique": k, "valeur": v, "unite": d["unite"], "statut": "MESURÉ"})

    # --- mode de prise en charge : métriques par classe, référence majoritaire, calibration (copie isolée) ---
    classes = res["capacite"]["classes"]
    yc, pc = pred[PREP.CIBLE_CAPACITE].values, pred["capacite_predite"].values
    pr, rc, f1, sup = precision_recall_fscore_support(yc, pc, labels=classes)
    lignes.append({"modele": "capacite_modele", "metrique": "accuracy", "valeur": res["capacite"]["accuracy"], "statut": "MESURÉ"})
    for k, c in enumerate(classes):
        for m, v in (("precision", pr[k]), ("rappel", rc[k]), ("f1", f1[k]), ("effectif_test", int(sup[k]))):
            lignes.append({"modele": "capacite_modele", "metrique": f"{m}_{c}", "valeur": v, "statut": "MESURÉ"})
    majo = tr[PREP.CIBLE_CAPACITE].mode()[0]
    lignes.append({"modele": "capacite_ref_majoritaire", "metrique": "accuracy", "valeur": float((yc == majo).mean()),
                   "statut": "MESURÉ", "unite": f"classe {majo}"})
    for (i, j), n in np.ndenumerate(np.array(res["capacite"]["confusion"])):
        lignes.append({"modele": "capacite_modele", "metrique": f"confusion_reel_{classes[i]}_predit_{classes[j]}",
                       "valeur": int(n), "statut": "MESURÉ"})
    xtr = PREP.vers_categories(tr[PREP.CAT_COLS + PREP.NUM_COLS])
    xte = PREP.vers_categories(te[PREP.CAT_COLS + PREP.NUM_COLS], reference=xtr)
    clf = PREP.modele(True, True).fit(xtr, tr[PREP.CIBLE_CAPACITE])
    proba_amb = clf.predict_proba(xte)[:, list(clf.classes_).index("ambulatoire")]
    vrai_amb = (te[PREP.CIBLE_CAPACITE].values == "ambulatoire").astype(int)
    lignes.append({"modele": "capacite_modele", "metrique": "brier_ambulatoire", "valeur": brier_score_loss(vrai_amb, proba_amb), "statut": "MESURÉ"})
    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(proba_amb, bins) - 1, 0, 9)
    calib = [{"tranche": f"{bins[k]:.1f}-{bins[k+1]:.1f}", "n": int((idx == k).sum()),
              "proba_moyenne": float(proba_amb[idx == k].mean()) if (idx == k).any() else float("nan"),
              "frequence_observee": float(vrai_amb[idx == k].mean()) if (idx == k).any() else float("nan")} for k in range(10)]
    ecrire_csv(AGREGEES / "ml_calibration.csv", calib)

    # --- erreurs par sous-groupe (effectifs >= 100 seulement) ---
    sg = []
    e_min = (pb - yb) * 60
    tranches = pd.cut(yb * 60, [0, 60, 120, 1e9], labels=["< 1 h", "1-2 h", "> 2 h"])
    for nom, cle in (("tranche_duree_reelle", tranches), ("mode_reel", pred[PREP.CIBLE_CAPACITE].values),
                     ("type_intervention", pred["type_intervention"].values)):
        s = pd.DataFrame({"g": cle, "e": e_min})
        for g, d in s.groupby("g", observed=True):
            if len(d) >= 100:
                sg.append({"variable": nom, "groupe": str(g), "n": len(d), "mae_min": float(d.e.abs().mean()),
                           "erreur_signee_moyenne_min": float(d.e.mean()),
                           "part_sous_estimation_pct": float((d.e < 0).mean() * 100)})
    ecrire_csv(AGREGEES / "ml_erreurs_sous_groupes.csv", sg)

    # --- règle d'urgence (D8) : distribution du score sur les séjours préparés (agrégée) ---
    dist = df["urgence"].value_counts().sort_index()
    from orchestre import ml as ML_SITE
    regle = [{"score_regle": int(s), "priorite_proposee": ML_SITE.priorite_depuis_score(int(s)), "sejours": int(n),
              "part_pct": 100 * n / len(df)} for s, n in dist.items()]
    ecrire_csv(AGREGEES / "ml_regle_urgence.csv", regle)

    # --- temps : chargement des modèles déployés et prédiction unitaire (cas fictif) ---
    import utilisation_modele as UM
    t2 = time.perf_counter()
    modeles = UM.charger_modeles_production()
    t_charge = time.perf_counter() - t2
    fictif = {"type_intervention": "Inconnu", "cim_diag_pr": "S720", "ccam_1": "NEKA020", "sexe": "2", "praticien": "CT",
              "anesth_type": "Inconnu", "anesth_loco_reg": "Inconnu", "age_annees": 80, "annee": 2026, "mois": 10,
              "jour_semaine": 1}
    durees = []
    for _ in range(50):
        t3 = time.perf_counter()
        UM.predire_patient(fictif, modeles)
        durees.append(time.perf_counter() - t3)
    temps = [{"composant": "ML préparation des données", "mesure": "temps réel (s)", "valeur": t_prep, "n": 1},
             {"composant": "ML évaluation (entraînement 4 copies + prédiction du test)", "mesure": "temps réel (s)", "valeur": t_eval, "n": 1},
             {"composant": "ML chargement des 4 modèles déployés", "mesure": "temps réel (s)", "valeur": t_charge, "n": 1},
             {"composant": "ML prédiction unitaire (4 modèles)", "mesure": "médiane (s)", "valeur": float(np.median(durees)), "n": 50},
             {"composant": "ML prédiction unitaire (4 modèles)", "mesure": "P95 (s)", "valeur": float(np.quantile(durees, .95)), "n": 50}]
    ecrire_csv(AGREGEES / "temps_ml.csv", temps)
    ecrire_csv(SORTIE / "ml_resultats.csv", lignes)

    # --- figures (densités agrégées, aucun point individuel) ---
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(17, 4.8), layout="constrained")
    for ax, (y, p, titre, u) in zip(axes, [(yb * 60, pb * 60, "Durée au bloc", "min"),
                                           (pred_lit["duree_avant_operation"], pred_lit["avant_j_predit"], "Nuits avant (hospitalisés)", "nuits"),
                                           (pred_lit["duree_apres_operation"], pred_lit["apres_j_predit"], "Nuits après (hospitalisés)", "nuits")]):
        lim = float(np.quantile(np.r_[y, p], 0.99))
        hb = ax.hexbin(y, p, gridsize=35, extent=(0, lim, 0, lim), mincnt=5, cmap="Greys", bins="log")
        ax.plot([0, lim], [0, lim], "r--", lw=1, label="y = x")
        ax.set(xlabel=f"Réel ({u})", ylabel=f"Prédit ({u})", title=f"{titre} (n = {len(y)})")
        ax.legend(loc="upper left")
        fig.colorbar(hb, ax=ax, label="séjours par case (≥ 5)")
    fig.suptitle("Réel vs prédit sur le jeu de test (densité ; cases de moins de 5 séjours masquées)")
    f1_ = sauver_figure(fig, "ml_reel_predit")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    axes[0].hist(np.clip(e_min, -180, 180), bins=72, color="0.4")
    axes[0].axvline(0, color="r", ls="--")
    axes[0].set(xlabel="Erreur prédit − réel (min), bornée à ±180", ylabel="Séjours",
                title=f"Résidus de la durée au bloc (n = {len(e_min)})")
    cm = np.array(res["capacite"]["confusion"])
    axes[1].imshow(cm, cmap="Greys")
    for (i, j), n in np.ndenumerate(cm):
        axes[1].text(j, i, f"{n}", ha="center", va="center", color="red", fontsize=12)
    axes[1].set(xticks=range(len(classes)), yticks=range(len(classes)), xticklabels=classes, yticklabels=classes,
                xlabel="Prédit", ylabel="Réel", title=f"Mode de prise en charge (n = {len(yc)})")
    f2_ = sauver_figure(fig, "ml_residus_confusion")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 4.5))
    cal = [c for c in calib if c["n"] > 0]
    ax.plot([c["proba_moyenne"] for c in cal], [c["frequence_observee"] for c in cal], "ko-")
    ax.plot([0, 1], [0, 1], "r--", lw=1)
    ax.set(xlabel="Probabilité prédite « ambulatoire »", ylabel="Fréquence observée", title="Calibration (10 tranches)")
    f3_ = sauver_figure(fig, "ml_calibration")
    plt.close(fig)
    for produit, fichiers in (("F1 réel/prédit", f1_), ("F1 résidus + confusion", f2_), ("F1 calibration", f3_)):
        enregistrer_manifeste(produit, ["ml_resultats.csv", "donnees_agregees/ml_calibration.csv"], SCRIPT,
                              note=", ".join(fichiers))
    enregistrer_manifeste("T2 / ml_resultats.csv", ["ml_resultats.csv"], SCRIPT)
    print(f"ML : {len(df)} séjours, test {res['n_test']}, évaluation {t_eval:.1f} s")
    return res


if __name__ == "__main__":
    main()
