# -*- coding: utf-8 -*-
"""
Onglet CONSULTATION : saisie des données d'entrée du modèle de machine learning, prédictions (capacité, durée
opératoire, nuits pré/post-opératoires) et priorité proposée par la règle d'urgence du projet, validation par le
chirurgien, puis insertion dans le programme par le système multi-agent (propositions de créneaux).
"""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from orchestre import ml
from orchestre import programme as P
from orchestre import sma_service as S
from orchestre import stockage as DB
from vues import commun as C

ETAT = "consultation"           # clé de session pour le parcours en 3 étapes


def _etat() -> dict:
    return st.session_state.setdefault(ETAT, {"etape": 1})


def _reinitialiser() -> None:
    st.session_state[ETAT] = {"etape": 1}


def afficher() -> None:
    C.entete("Consultation")
    if msg := st.session_state.pop("flash", None):
        st.success(msg + " Retrouvez-le dans l'onglet Patients.")
    e = _etat()
    etapes = ["1. Données de consultation", "2. Prédictions et validation", "3. Choix du créneau"]
    st.markdown(" ".join(C.badge(t, "bleu" if i + 1 == e["etape"] else "") for i, t in enumerate(etapes)),
                unsafe_allow_html=True)
    st.write("")
    if e["etape"] == 1:
        _etape_saisie()
    elif e["etape"] == 2:
        _etape_validation()
    else:
        _etape_creneaux()


# =============================================================================
# Étape 1 : saisie
# =============================================================================

def _etape_saisie() -> None:
    e = _etat()
    voc = ml.vocabulaires()
    u = C.utilisateur()
    praticiens = P.praticiens_v28()
    anc = e.get("saisie", {})
    demain = C.maintenant().date() + timedelta(days=1)

    with st.form("saisie_consultation"):
        st.markdown("#### Patient")
        st.caption("Ne saisissez **ni nom ni prénom** : le patient sera identifié par un pseudonyme "
                   "(PAT-AA-NNNN). La référence de dossier est facultative et chiffrée.")
        c1, c2, c3 = st.columns([1, 1, 1.4])
        age = c1.number_input("Âge (années)", 0, 110, int(anc.get("age", 50)), help="Variable « age_annees » du modèle. "
                              "L'âge suffit : la date de naissance n'est pas collectée (minimisation).")
        sexe = c2.radio("Sexe", ["1", "2"], format_func=ml.LIBELLES_SEXE.get, horizontal=True,
                        index=["1", "2"].index(anc.get("sexe", "1")))
        reference = c3.text_input("Référence de dossier (IPP) — facultatif", value=anc.get("reference", ""),
                                  type="password", help="Stockée chiffrée, visible uniquement sur demande (accès tracé).")

        st.markdown("#### Diagnostic et acte")
        c1, c2 = st.columns(2)
        cim = c1.selectbox("Diagnostic principal (CIM-10)", voc["cim_diag_pr"], index=_index(voc["cim_diag_pr"], anc.get("cim")),
                           format_func=lambda c: ml.avec_libelle(c, "cim"), accept_new_options=True,
                           placeholder="ex. gonarthrose ou M17.1 — tapez pour filtrer",
                           help="Liste = codes connus du modèle, recherche par mot ou par code. Un autre code reste "
                                "possible (fiabilité réduite).")
        ccam = c2.selectbox("Acte principal (CCAM)", voc["ccam_1"], index=_index(voc["ccam_1"], anc.get("ccam")),
                            format_func=lambda c: ml.avec_libelle(c, "ccam"), accept_new_options=True,
                            placeholder="ex. prothèse totale du genou ou NFKA008 — tapez pour filtrer")
        interv = st.selectbox("Type d'intervention", voc["type_intervention"],
                              index=_index(voc["type_intervention"], anc.get("interv")), accept_new_options=True,
                              placeholder="ex. Prothese Totale Genou — tapez pour filtrer")

        st.markdown("#### Chirurgien et anesthésie")
        c1, c2, c3 = st.columns(3)
        if u["role"] == "chirurgien" and u.get("praticien") in praticiens:
            prat = u["praticien"]
            c1.text_input("Chirurgien", value=f"Dr {prat}", disabled=True)
        else:
            prat = c1.selectbox("Chirurgien", praticiens, index=_index(praticiens, anc.get("praticien")) or 0,
                                format_func=lambda x: f"Dr {x}")
        anesth = c2.selectbox("Type d'anesthésie", voc["anesth_type"], index=_index(voc["anesth_type"], anc.get("anesth")),
                              placeholder="Choisir…")
        loco_opts = ["Aucune / non renseignée"] + voc["anesth_loco_reg"]
        loco = c3.selectbox("Anesthésie loco-régionale", loco_opts, index=_index(loco_opts, anc.get("loco")) or 0)

        st.markdown("#### Programmation")
        c1, c2 = st.columns(2)
        date_min = c1.date_input("Opérable au plus tôt le", value=max(demain, anc.get("date_min", demain)),
                                 min_value=demain, format="DD/MM/YYYY",
                                 help="Sert aussi aux variables calendaires du modèle (année, mois, jour de semaine).")
        confrere = c2.checkbox("Accepter un confrère de même spécialité", value=anc.get("confrere", False),
                               help="Élargit les créneaux proposés (coût de changement de chirurgien pris en compte).")
        info = st.checkbox("Le patient a été informé de l'utilisation de ses données pour la programmation "
                           "(notice : onglet Confidentialité).", value=anc.get("info", False))
        envoye = st.form_submit_button("Calculer les prédictions", type="primary", width="stretch")

    if not envoye:
        return
    erreurs = []
    if not cim or not interv or not ccam or not anesth:
        erreurs.append("Renseignez le diagnostic, l'acte, le type d'intervention et l'anesthésie.")
    else:
        erreurs += ml.verifier_codes(cim, ccam)
    if not info:
        erreurs.append("Confirmez l'information du patient (art. 13 RGPD).")
    if erreurs:
        st.error("\n".join(f"- {x}" for x in erreurs))
        return
    loco_val = ml.INCONNU if loco.startswith("Aucune") else loco
    entrees = ml.entrees_modele(type_intervention=interv, cim_diag_pr=cim, ccam_1=ccam, sexe=sexe, praticien=prat,
                                anesth_type=anesth, anesth_loco_reg=loco_val, age_annees=age, date_intervention=date_min)
    pred = ml.predire(entrees)
    e.update(etape=2, prediction=pred, saisie=dict(age=age, sexe=sexe, reference=reference, cim=cim, ccam=ccam,
                                                   interv=interv, praticien=prat, anesth=anesth, loco=loco,
                                                   date_min=date_min, confrere=confrere, info=info))
    C.tracer("prédiction ML (consultation)", f"Dr {prat}")
    st.rerun()


def _index(liste, valeur):
    try:
        return liste.index(valeur)
    except (ValueError, TypeError):
        return None


# =============================================================================
# Étape 2 : prédictions et validation
# =============================================================================

def _etape_validation() -> None:
    e = _etat()
    pred: ml.Prediction = e["prediction"]
    s = e["saisie"]
    met = ml.metriques()

    st.markdown("#### Ce que prédit le modèle")
    if pred.hors_vocabulaire:
        st.warning("Valeurs jamais vues à l'entraînement : " + ", ".join(pred.hors_vocabulaire)
                   + ". Le modèle les traite comme manquantes : vérifiez attentivement les prédictions.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prise en charge", "Ambulatoire" if pred.ambulatoire else "Hospitalisation",
              f"{pred.proba_ambulatoire if pred.ambulatoire else 1 - pred.proba_ambulatoire:.0%} de confiance",
              delta_color="off", delta_arrow="off")
    c2.metric("Durée au bloc", f"{pred.duree_bloc_min} min",
              f"± {met['duree_bloc_heures']['mae'] * 60:.0f} min (erreur moyenne)" if met else None, delta_color="off", delta_arrow="off")
    c3.metric("Nuits avant / après", "—" if pred.ambulatoire else f"{pred.nuits_pre_op} / {pred.nuits_post_op}",
              f"± {met['nuits_apres']['mae']:.1f} nuit après" if met else None, delta_color="off", delta_arrow="off")
    c4.metric("Priorité proposée", ml.LIBELLES_PRIORITE[pred.priorite], f"règle du projet : {pred.score_urgence} / 10",
              delta_color="off", delta_arrow="off",
              help="Calculée par une règle du projet à partir des codes CIM-10 et CCAM (traumatologie, infections...) ; "
                   "ce n'est pas un score d'urgence validé cliniquement. Validez ou corrigez la priorité ci-dessous.")
    if met:
        st.caption(f"Qualité mesurée sur les 20 % de séjours jamais vus à l'entraînement ({met['n_test']:,} séjours) : "
                   f"capacité juste à {met['capacite']['accuracy']:.0%}, durée de bloc R² = "
                   f"{met['duree_bloc_heures']['r2']:.2f}, nuits post-op à ±1 nuit dans "
                   f"{met['apres_erreur_le_1j_pct']:.0f} % des cas. Ce sont des **suggestions** : "
                   f"vous gardez la décision.".replace(",", " "))
    if pred.score_urgence >= 8:
        st.error("La règle d'urgence du projet donne un score élevé (≥ 8) : si le patient doit être opéré dans les "
                 "24 h, déclarez-le plutôt dans l'onglet **Urgences** (gravité, délai d'incision, insertion immédiate).")

    st.markdown("#### Valeurs retenues pour la programmation")
    with st.form("validation"):
        c1, c2, c3, c4, c5 = st.columns([1.3, 1, 1, 1, 1.6])
        amb = c1.radio("Prise en charge", [True, False], index=0 if pred.ambulatoire else 1, horizontal=False,
                       format_func=lambda x: "Ambulatoire" if x else "Hospitalisation")
        duree = c2.number_input("Durée au bloc (min)", 15, 600, pred.duree_bloc_min, step=5)
        pre = c3.number_input("Nuits avant", 0, 10, pred.nuits_pre_op)
        post = c4.number_input("Nuits après", 0, 30, pred.nuits_post_op)
        prio = c5.selectbox("Priorité clinique", [1, 2, 3, 4], index=pred.priorite - 1, format_func=ml.LIBELLES_PRIORITE.get,
                            help="Proposée par la règle d'urgence du projet : à valider ou corriger par le médecin.")
        b1, b2 = st.columns(2)
        retour = b1.form_submit_button("Modifier la saisie", width="stretch")
        chercher = b2.form_submit_button("Rechercher des créneaux", type="primary", width="stretch")
    if retour:
        e["etape"] = 1
        st.rerun()
    if chercher:
        e["valide"] = {"ambulatoire": amb, "duree_bloc_min": int(duree), "nuits_pre_op": 0 if amb else int(pre),
                       "nuits_post_op": 0 if amb else int(post), "priorite": int(prio),
                       "date_min": s["date_min"].isoformat(), "modifie_par_chirurgien": (
                           amb != pred.ambulatoire or duree != pred.duree_bloc_min or prio != pred.priorite
                           or (not amb and (pre != pred.nuits_pre_op or post != pred.nuits_post_op)))}
        e["etape"] = 3
        e.pop("propositions", None)
        st.rerun()


# =============================================================================
# Étape 3 : créneaux proposés par le SMA
# =============================================================================

def _patient_provisoire(e: dict) -> "S.SC.Patient":
    fiche = {"id": 0, "pseudo": "Nouveau patient", "praticien": e["saisie"]["praticien"],
             "entrees": e["prediction"].entrees}
    return S.patient_consultation(fiche, e["valide"])


def _etape_creneaux() -> None:
    e = _etat()
    sim = C.simulation()
    if sim is None:
        st.error("Aucun programme opératoire n'est disponible (voir Planning).")
        return
    s, v = e["saisie"], e["valide"]
    patient = _patient_provisoire(e)
    if "propositions" not in e:
        with C.VERROU_SIM:
            e["propositions"] = S.proposer_creneaux(sim, patient, s["date_min"], s["confrere"])
    props = e["propositions"]
    st.markdown(f"#### Créneaux proposés pour Dr {s['praticien']} — {v['duree_bloc_min']} min, "
                f"{'ambulatoire' if v['ambulatoire'] else 'hospitalisation'}, priorité {v['priorite']}")
    st.caption("Chaque salle a répondu à l'appel d'offres de l'agent de régulation ; les agents Chirurgien et "
               "Hébergement ont validé la disponibilité. Classement par coût croissant (report, décalages, "
               "déprogrammations, lits).")
    noms = C.noms_patients(sim)

    if not props:
        st.warning("Aucun créneau compatible n'a été trouvé (chirurgien sans vacation ou durée supérieure à ses "
                   "vacations ?). Vérifiez les valeurs, ou inscrivez le patient : le système retentera de le placer.")
    cols = st.columns(max(1, min(4, len(props))))
    for i, (col, p) in enumerate(zip(cols, props)):
        with col, st.container(border=True):
            st.markdown(f"**{C.jour_long(p['jour'])}**" + (" " + C.badge("recommandé", "vert") if i == 0 else ""),
                            unsafe_allow_html=True)
            st.markdown(f"**{p['debut']:%H:%M} – {p['fin']:%H:%M}**  \n{p['salle']} · vacation {p['vacation']}  \n"
                        f"Dr {p['chirurgien']}" + (" " + C.badge("confrère", "ambre") if p["changement_chirurgien"] else ""),
                        unsafe_allow_html=True)
            st.markdown(f"<span class='petit'>Lits ce jour : {p['lits_jour']} · ambulatoire : {p['places_jour']}</span>",
                        unsafe_allow_html=True)
            impacts = []
            if p["deplaces"]:
                impacts.append(f"{len(p['deplaces'])} patient(s) décalé(s) dans la vacation")
            for x in p["evinces"]:
                impacts.append(f"{C.lisible(x['patient'], noms)} (priorité {x['priorite']}) serait reprogrammé")
            if p["hebergement"] != "capacité OK":
                impacts.append(f"Hébergement : {p['hebergement']}")
            st.markdown("<br>".join(f"<span class='petit'>{t}</span>" for t in impacts) or
                        "<span class='petit'>Aucun impact sur les autres patients</span>", unsafe_allow_html=True)
            st.caption(f"Coût SMA : {p['cout']:,.0f}".replace(",", " "))
            if st.button("Retenir ce créneau", key=f"choix_{i}", type="primary" if i == 0 else "secondary",
                         width="stretch"):
                _inscrire(e, p)

    st.write("")
    c1, c2, c3 = st.columns(3)
    if c1.button("Modifier les valeurs", width="stretch"):
        e["etape"] = 2
        st.rerun()
    # le planning des vacations est fixe sur toutes les semaines à venir : un créneau existe toujours, plus de
    # « liste d'attente » au choix ; ce bouton ne sert qu'en l'absence totale de proposition
    if not props and c2.button("Inscrire quand même", width="stretch",
                               help="Le système cherchera lui-même un créneau, et retentera s'il n'en trouve pas."):
        _inscrire(e, None)
    if c3.button("Abandonner (rien n'est enregistré)", width="stretch"):
        _reinitialiser()
        st.rerun()


def _inscrire(e: dict, proposition) -> None:
    u = C.utilisateur()
    s, v, pred = e["saisie"], e["valide"], e["prediction"]
    fiche = DB.creer_patient(praticien=s["praticien"], entrees=pred.entrees, prediction=pred.resume(), valide=v,
                             reference=s["reference"], information_patient=s["info"], auteur=u["login"])
    fiche_complete = DB.patient(fiche["id"])
    patient = S.patient_consultation(fiche_complete, v)
    chirs = S.chirurgiens_possibles(patient, s["confrere"])
    contenu = {"patient": S.patient_vers_dict(patient), "jour_min": s["date_min"].isoformat(), "chirurgiens": chirs,
               "salle_id": proposition["salle_id"] if proposition else None,
               "fenetre_id": proposition["fenetre_id"] if proposition else None}
    if proposition is None:
        contenu["attente"] = True
    if proposition:
        choix = (f"Créneau choisi : {proposition['salle']}, {C.jour_long(proposition['jour'])} "
                 f"{proposition['debut']:%H:%M}, Dr {proposition['chirurgien']}")
    else:
        choix = "Inscription en liste d'attente (aucun créneau réservé)"
    sim = C.appliquer(lambda: DB.ajouter_evenement(C.maintenant(), "inscription", contenu, u["login"], fiche["id"]),
                      categorie="Programme", action="Inscription au programme", patient=fiche["pseudo"],
                      detail=choix, motif=f"Consultation de Dr {s['praticien']}, priorité clinique {v['priorite']}")
    C.synchroniser_statuts(sim)
    it = sim.intervention(patient.id)
    _reinitialiser()
    if it is not None:
        st.session_state["flash"] = (f"{fiche['pseudo']} programmé(e) le {C.jour_long(it.debut.date())} à "
                                     f"{it.debut:%H:%M} ({sim.modele.salles[it.salle_id].nom_affiche}, "
                                     f"{S.nom_chirurgien(it.chirurgien_id)}).")
    else:
        st.session_state["flash"] = f"{fiche['pseudo']} inscrit(e) en liste d'attente."
    st.rerun()
