# -*- coding: utf-8 -*-
"""Onglet PATIENTS : fiches de consultation, statut dans le programme, annulation, droits RGPD."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from orchestre import ml
from orchestre import sma_service as S
from orchestre import stockage as DB
from vues import commun as C


def afficher() -> None:
    u = C.utilisateur()
    chir = u["role"] == "chirurgien"
    C.entete(("Mes patients" if chir else "Patients"),
             "Patients inscrits depuis l'onglet Consultation (pseudonymisés). Les patients DEMO-xxxx du programme "
             "initial sont fictifs et n'apparaissent pas ici.")
    sim = C.simulation()
    if sim:
        C.synchroniser_statuts(sim)
    fiches = DB.lister_patients(u["praticien"] if chir else None)
    C.tracer("consultation de la liste des patients", f"{len(fiches)} fiche(s)")
    if not fiches:
        st.info("Aucun patient pour le moment. Utilisez l'onglet **Consultation** pour en inscrire un.")
        return

    lignes = []
    for f in fiches:
        it = sim.intervention(S.pid_consultation(f["id"])) if sim else None
        v = f["valide"]
        lignes.append({"Pseudonyme": f["pseudo"], "Chirurgien": f"Dr {f['praticien']}",
                       "Intervention": f["entrees"].get("type_intervention", ""),
                       "Durée (min)": v.get("duree_bloc_min"), "Prise en charge": "Ambulatoire" if v.get("ambulatoire") else "Hospit.",
                       "Priorité": v.get("priorite"), "Statut": f["statut"],
                       "Programmé le": f"{C.jour_long(it.debut.date())} {it.debut:%H:%M}" if it else "—",
                       "Salle": sim.modele.salles[it.salle_id].nom_affiche if it else "—",
                       "Créé le": f["cree_le"][:16].replace("T", " ")})
    st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")

    st.markdown("#### Détail d'un patient")
    choix = st.selectbox("Patient", fiches, format_func=lambda f: f"{f['pseudo']} — {f['entrees'].get('type_intervention', '')}")
    if not choix:
        return
    _detail(choix, sim)


def _detail(f: dict, sim) -> None:
    u = C.utilisateur()
    peut_modifier = u["role"] in ("regulation", "admin") or u.get("praticien") == f["praticien"]
    p, v, e = f["prediction"], f["valide"], f["entrees"]
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("**Données de consultation (entrées du modèle)**")
        st.markdown(f"Âge {e.get('age_annees', '?'):.0f} ans · {ml.LIBELLES_SEXE.get(str(e.get('sexe')), '?')}  \n"
                    f"CIM-10 **{ml.avec_libelle(e.get('cim_diag_pr'), 'cim')}**  \n"
                    f"CCAM **{ml.avec_libelle(e.get('ccam_1'), 'ccam')}**  \n"
                    f"{e.get('type_intervention')}  \nAnesthésie : {e.get('anesth_type')} / {e.get('anesth_loco_reg')}")
    with c2.container(border=True):
        st.markdown("**Prédiction du modèle → valeur retenue**")
        st.markdown(
            f"Prise en charge : {'amb.' if p.get('ambulatoire') else 'hospit.'} → **{'ambulatoire' if v.get('ambulatoire') else 'hospitalisation'}**  \n"
            f"Durée : {p.get('duree_bloc_min')} min → **{v.get('duree_bloc_min')} min**  \n"
            f"Nuits avant/après : {p.get('nuits_pre_op')}/{p.get('nuits_post_op')} → **{v.get('nuits_pre_op')}/{v.get('nuits_post_op')}**  \n"
            f"Urgence : {p.get('score_urgence')}/10 → **priorité {v.get('priorite')}**"
            + ("  \n" + C.badge("valeurs corrigées par le chirurgien", "ambre") if v.get("modifie_par_chirurgien") else ""),
            unsafe_allow_html=True)

    it = sim.intervention(S.pid_consultation(f["id"])) if sim else None
    if it:
        st.success(f"Programmé le {C.jour_long(it.debut.date())} de {it.debut:%H:%M} à {it.fin:%H:%M} — "
                   f"{sim.modele.salles[it.salle_id].nom_affiche}, Dr {S.code_chirurgien(it.chirurgien_id)}"
                   + (f" (initialement {it.debut_initial:%d/%m %H:%M})" if it.debut != it.debut_initial else ""))

    b1, b2, b3, b4 = st.columns(4)
    if f["a_reference"] and b1.button("Afficher la référence dossier", width="stretch"):
        C.tracer("affichage de la référence dossier (déchiffrement)", f["pseudo"])
        st.info(f"Référence dossier : {DB.reference_dossier(f['id'])}")
    if peut_modifier and f["statut"] in ("programmé", "liste d'attente"):
        with b2.popover("Annuler l'intervention", width="stretch"):
            motif = st.text_input("Motif de l'annulation (obligatoire, tracé)", key=f"motif_ann_{f['id']}",
                                  placeholder="ex. contre-indication anesthésique, souhait du patient")
            if st.button("Confirmer l'annulation", type="primary", key=f"ann_{f['id']}", disabled=not motif.strip()):
                C.appliquer(lambda: DB.ajouter_evenement(
                    C.maintenant(), "annulation", {"pid": S.pid_consultation(f["id"]), "nom": f["pseudo"],
                                                   "motif": motif.strip()}, u["login"], f["id"]),
                    categorie="Programme", action="Annulation d'intervention", patient=f["pseudo"],
                    motif=motif.strip())
                st.rerun()
    donnees = DB.exporter_patient(f["id"])
    if b3.download_button("Exporter (droit d'accès)", json.dumps(donnees, ensure_ascii=False, indent=2, default=str),
                          file_name=f"{f['pseudo']}.json", mime="application/json", width="stretch"):
        C.tracer("export des données patient (droit d'accès)", f["pseudo"])
    if peut_modifier:
        with b4.popover("Supprimer (droit à l'effacement)", width="stretch"):
            st.write("Supprime la fiche et ses événements ; le SMA rejoue le programme sans ce patient. Irréversible. "
                     "L'historique conserve le pseudonyme et le motif (obligation de traçabilité).")
            motif_s = st.text_input("Motif (obligatoire, tracé)", key=f"motif_sup_{f['id']}",
                                    placeholder="ex. demande d'effacement du patient")
            if st.button("Confirmer la suppression", type="primary", key=f"sup_{f['id']}",
                         disabled=not motif_s.strip()):
                C.appliquer(lambda: DB.supprimer_patient(f["id"]), categorie="Données patient",
                            action="Suppression de la fiche (droit à l'effacement)", patient=f["pseudo"],
                            motif=motif_s.strip())
                st.rerun()
