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

A_VENIR = ("programmé", "liste d'attente", "à programmer", "urgence à venir")


def afficher() -> None:
    u = C.utilisateur()
    chir = u["role"] == "chirurgien"
    C.entete("Mes patients" if chir else "Patients")
    if msg := st.session_state.pop("flash_patient", None):
        st.success(msg)
    sim = C.simulation()
    if sim:
        C.synchroniser_statuts(sim)
    fiches = DB.lister_patients(u["praticien"] if chir else None)
    urgences = _lignes_urgences(sim, u["praticien"] if chir else None)
    if chir:                            # un chirurgien ne voit que ses patients à venir (pas les opérés ni annulés)
        fiches = [f for f in fiches if f["statut"] in A_VENIR]
        urgences = [l for l in urgences if l["Statut"] in A_VENIR]
    C.tracer("consultation de la liste des patients", f"{len(fiches)} fiche(s), {len(urgences)} urgence(s)")
    if not fiches and not urgences:
        st.info("Aucun patient à venir. Utilisez l'onglet **Consultation** pour en inscrire un." if chir else
                "Aucun patient pour le moment. Utilisez l'onglet **Consultation** pour en inscrire un.")
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
    st.dataframe(pd.DataFrame(lignes + [{k: v for k, v in l.items() if k != "_evt"} for l in urgences]),
                 hide_index=True, width="stretch")

    st.markdown("#### Détail d'un patient")
    options = [("fiche", f) for f in fiches] + [("urgence", l) for l in urgences]
    i = st.selectbox("Patient", range(len(options)), format_func=lambda i: (
        f"{options[i][1]['pseudo']} — {options[i][1]['entrees'].get('type_intervention', '')}" if options[i][0] == "fiche"
        else f"{options[i][1]['Pseudonyme']} — {options[i][1]['Intervention']} (urgence)"))
    if i is None:
        return
    choix = options[i]
    if choix[0] == "fiche":
        _detail(choix[1], sim)
    else:
        _detail_urgence(choix[1], sim)


def _lignes_urgences(sim, praticien) -> list[dict]:
    """Patients déclarés en urgence (événements du SMA, sans fiche de consultation). Pour un chirurgien : ceux
    qu'il a vus ou qu'il opère."""
    lignes = []
    for e in DB.lister_evenements():
        if e["type"] != "urgence":
            continue
        p = e["contenu"]["patient"]
        it = sim.intervention(p["id"]) if sim else None
        vu_par = S.code_chirurgien(p["chirurgien_id"])
        operateur = S.code_chirurgien(it.chirurgien_id) if it else vu_par
        if praticien and praticien not in (vu_par, operateur):
            continue
        if sim is None or e["heure"] > sim.maintenant:
            statut = "urgence à venir"
        elif it is None:
            statut = "urgence non programmée"
        else:
            statut = "opéré" if it.fin <= sim.maintenant else "programmé"
        lignes.append({"Pseudonyme": p.get("nom") or f"P{p['id']}",
                       "Chirurgien": S.nom_chirurgien(it.chirurgien_id if it else p["chirurgien_id"]),
                       "Intervention": p.get("type_intervention") or "Urgence",
                       "Durée (min)": p.get("duree_bloc"),
                       "Prise en charge": "Ambulatoire" if p.get("ambulatoire") else "Hospit.",
                       "Priorité": p.get("priorite"), "Statut": statut,
                       "Programmé le": f"{C.jour_long(it.debut.date())} {it.debut:%H:%M}" if it else "—",
                       "Salle": sim.modele.salles[it.salle_id].nom_affiche if it else "—",
                       "Créé le": f"{e['heure']:%Y-%m-%d %H:%M}", "_evt": e})
    return lignes


def _detail_urgence(l: dict, sim) -> None:
    """Fiche d'une urgence : pas de consultation ni de prédiction enregistrée, seulement la déclaration."""
    e = l["_evt"]
    p, gravite = e["contenu"]["patient"], e["contenu"].get("gravite", "")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("**Déclaration de l'urgence**")
        st.markdown(f"{S.LIBELLES_GRAVITE.get(gravite, gravite)}  \n"
                    f"Déclarée le {C.jour_long(e['heure'].date()).lower()} à {e['heure']:%H:%M} par {e['auteur']}  \n"
                    f"Vue par {S.nom_chirurgien(p['chirurgien_id'])}  \n"
                    f"Motif : {p.get('type_intervention') or 'non renseigné'}")
    with c2.container(border=True):
        st.markdown("**Prise en charge prévue**")
        st.markdown(f"Durée estimée : **{p.get('duree_bloc')} min**  \n"
                    + ("**Ambulatoire**" if p.get("ambulatoire") else
                       f"**Hospitalisation**, {p.get('nuits_post_op', 0)} nuit(s) après")
                    + (f"  \nCIM-10 : {ml.avec_libelle(p['diagnostic'], 'cim')}" if p.get("diagnostic") else ""))
    it = sim.intervention(p["id"]) if sim else None
    if it:
        st.success(f"Programmé le {C.jour_long(it.debut.date())} de {it.debut:%H:%M} à {it.fin:%H:%M} — "
                   f"{sim.modele.salles[it.salle_id].nom_affiche}, {l['Chirurgien']}")
    else:
        st.info(f"Statut : {l['Statut']}.")


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
                   f"{sim.modele.salles[it.salle_id].nom_affiche}, {S.nom_chirurgien(it.chirurgien_id)}"
                   + (f" (initialement {it.debut_initial:%d/%m %H:%M})" if it.debut != it.debut_initial else ""))

    b1, b2, b3, b4 = st.columns(4)
    if f["a_reference"] and b1.button("Afficher la référence dossier", width="stretch"):
        C.tracer("affichage de la référence dossier (déchiffrement)", f["pseudo"])
        st.info(f"Référence dossier : {DB.reference_dossier(f['id'])}")
    it = sim.intervention(S.pid_consultation(f["id"])) if sim else None
    commencee = it is not None and it.debut <= sim.maintenant
    if peut_modifier and f["statut"] in ("programmé", "liste d'attente") and commencee:
        b2.button("Annuler l'intervention", width="stretch", disabled=True,
                  help="L'intervention a déjà commencé : elle ne peut plus être annulée.")
    elif peut_modifier and f["statut"] in ("programmé", "liste d'attente"):
        with b2.popover("Annuler l'intervention", width="stretch"):
            st.write("Retire le patient du programme opératoire et libère son créneau : la régulation le propose "
                     "aussitôt aux patients de la liste d'attente. La fiche est conservée avec le statut « annulé ».")
            # formulaire : le motif est transmis en même temps que le clic (sinon le 1er clic est perdu)
            with st.form(f"form_ann_{f['id']}", border=False):
                motif = st.text_input("Motif de l'annulation (obligatoire, tracé)",
                                      placeholder="ex. contre-indication anesthésique, souhait du patient")
                ok = st.form_submit_button("Confirmer l'annulation", type="primary", width="stretch")
            if ok and not motif.strip():
                st.error("Indiquez le motif de l'annulation.")
            elif ok:
                C.appliquer(lambda: DB.ajouter_evenement(
                    C.maintenant(), "annulation", {"pid": S.pid_consultation(f["id"]), "nom": f["pseudo"],
                                                   "motif": motif.strip()}, u["login"], f["id"]),
                    categorie="Programme", action="Annulation d'intervention", patient=f["pseudo"],
                    motif=motif.strip())
                st.session_state["flash_patient"] = f"Intervention de {f['pseudo']} annulée : créneau libéré."
                st.rerun()
    donnees = DB.exporter_patient(f["id"])
    if b3.download_button("Exporter (droit d'accès)", json.dumps(donnees, ensure_ascii=False, indent=2, default=str),
                          file_name=f"{f['pseudo']}.json", mime="application/json", width="stretch"):
        C.tracer("export des données patient (droit d'accès)", f["pseudo"])
    if peut_modifier:
        with b4.popover("Supprimer (droit à l'effacement)", width="stretch"):
            st.write("Supprime la fiche et ses événements ; le SMA rejoue le programme sans ce patient. Irréversible. "
                     "L'historique conserve le pseudonyme et le motif (obligation de traçabilité).")
            with st.form(f"form_sup_{f['id']}", border=False):
                motif_s = st.text_input("Motif (obligatoire, tracé)", placeholder="ex. demande d'effacement du patient")
                ok_s = st.form_submit_button("Confirmer la suppression", type="primary", width="stretch")
            if ok_s and not motif_s.strip():
                st.error("Indiquez le motif de la suppression.")
            elif ok_s:
                C.appliquer(lambda: DB.supprimer_patient(f["id"]), categorie="Données patient",
                            action="Suppression de la fiche (droit à l'effacement)", patient=f["pseudo"],
                            motif=motif_s.strip())
                st.rerun()
