# -*- coding: utf-8 -*-
"""
Onglet URGENCES : gestion dynamique par le système multi-agent.
  * déclarer une urgence (gravité, délai d'incision) -> triage, appel d'offres aux salles, décision ;
  * déclarer un incident logistique (panne / prolongation / fin de panne du monte-lit) ;
  * suivre les décisions, les alertes et les messages échangés par les agents.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from orchestre import ml
from orchestre import programme as P
from orchestre import sma_service as S
from orchestre import stockage as DB
from vues import commun as C


def afficher() -> None:
    C.entete("Urgences et aléas")
    sim = C.simulation()
    if sim is None:
        st.error("Aucun programme opératoire disponible.")
        return
    noms = C.noms_patients(sim)
    _bandeau(sim, noms)
    t_abs = None
    if C.est("admin"):                  # traces internes du système multi-agent : administrateur uniquement
        t1, t_suivi, t2, t_abs, t3, t4 = st.tabs(["Déclarer une urgence", "Suivi des urgences", "Incident logistique",
                                                  "Absence d'un chirurgien", "Fil des décisions",
                                                  "Messages entre agents"])
        with t3:
            _fil(sim, noms)
        with t4:
            _messages(sim, noms)
    elif C.est("regulation"):
        t1, t_suivi, t2, t_abs = st.tabs(["Déclarer une urgence", "Suivi des urgences", "Incident logistique",
                                          "Absence d'un chirurgien"])
    else:
        t1, t2, t_abs = st.tabs(["Déclarer une urgence", "Incident logistique", "Mes absences"])
        t_suivi = None
    if t_abs is not None:
        with t_abs:
            u = C.utilisateur()
            if u["role"] == "chirurgien" and u.get("praticien") not in P.praticiens_v28():
                st.info("Aucun praticien n'est associé à ce compte : contactez l'administrateur.")
            else:
                _absences(sim, noms, u["praticien"] if u["role"] == "chirurgien" else None)
    if t_suivi is not None:
        with t_suivi:
            _suivi()
    with t1:
        _urgence(sim)
    with t2:
        _logistique(sim)


DUREE_ALERTE_MIN = 10           # une alerte reste encadrée en rouge 10 minutes, puis passe dans « Alertes du jour »


def _bandeau(sim: S.Simulation, noms) -> None:
    if msg := st.session_state.pop("flash_urgence", None):
        {"ok": st.success, "attention": st.warning}.get(msg[0], st.error)(msg[1])
    now = C.maintenant()
    alertes = [(h, a) for h, a in sim.alertes_horodatees() if "transfert vers un autre établissement" not in a]
    recentes = [(h, a) for h, a in alertes if now - timedelta(minutes=DUREE_ALERTE_MIN) <= h <= now]
    for h, a in recentes[-5:]:
        st.error(f"{h:%H:%M} — {C.lisible(a, noms)}")
    du_jour = [(h, a) for h, a in alertes if h.date() == now.date() and (h, a) not in recentes]
    if du_jour:
        with st.expander(f"Alertes du jour ({len(du_jour)})"):
            for h, a in reversed(du_jour):
                st.markdown(f"<div class='petit'><b>{h:%H:%M}</b> — {C.lisible(a, noms)}</div>", unsafe_allow_html=True)
    for asc, (deb, fin) in sim.pannes().items():
        st.warning(f"{S.ASCENSEURS.get(asc, asc)} en panne depuis {deb:%H:%M}, retour estimé {fin:%H:%M} : "
                   "les patients hospitalisés ne peuvent pas monter au bloc ni en redescendre.")


# =============================================================================
# Déclarer une urgence
# =============================================================================

def _urgence(sim: S.Simulation) -> None:
    u = C.utilisateur()
    praticiens = P.praticiens_v28()
    maintenant = C.maintenant()
    if not sim.jours() or maintenant.date() > sim.jours()[-1]:
        st.warning("L'heure courante est hors de l'horizon du programme.")
    st.caption(f"Arrivée enregistrée à l'heure courante : **{C.jour_long(maintenant.date())} {maintenant:%H:%M}**.")

    with st.expander("Estimer la durée et la prise en charge avec le modèle (facultatif)"):
        voc = ml.vocabulaires()
        with st.form("estimation_urgence"):
            c1, c2, c3 = st.columns(3)
            cim = c1.selectbox("CIM-10", voc["cim_diag_pr"], index=None, accept_new_options=True,
                               format_func=lambda c: ml.avec_libelle(c, "cim"), placeholder="ex. fracture du col ou S72.0")
            ccam = c2.selectbox("CCAM", voc["ccam_1"], index=None, accept_new_options=True,
                                format_func=lambda c: ml.avec_libelle(c, "ccam"), placeholder="ex. ostéosynthèse ou NBCA006")
            interv = c3.selectbox("Type d'intervention", voc["type_intervention"], index=None, accept_new_options=True,
                                  placeholder="Choisir ou saisir…")
            c1, c2, c3 = st.columns(3)
            age = c1.number_input("Âge", 0, 110, 50)
            sexe = c2.radio("Sexe", ["1", "2"], format_func=ml.LIBELLES_SEXE.get, horizontal=True)
            prat_e = c3.selectbox("Chirurgien", praticiens, format_func=lambda x: f"Dr {x}",
                                  index=praticiens.index(u["praticien"]) if u.get("praticien") in praticiens else 0)
            ok_e = st.form_submit_button("Estimer")
        if ok_e:
            ent = ml.entrees_modele(type_intervention=interv or "", cim_diag_pr=cim or "", ccam_1=ccam or "", sexe=sexe,
                                    praticien=prat_e, anesth_type=ml.INCONNU, anesth_loco_reg=ml.INCONNU,
                                    age_annees=age, date_intervention=maintenant.date())
            pr = ml.predire(ent)
            st.session_state["estim_urg"] = {"duree": pr.duree_bloc_min, "amb": pr.ambulatoire,
                                                      "post": max(1, pr.nuits_post_op), "cim": ent["cim_diag_pr"],
                                                      "interv": ent["type_intervention"], "prat": prat_e, "age": age}
            C.tracer("prédiction ML (urgence)")
            st.success(f"Estimation : {pr.duree_bloc_min} min, {'ambulatoire' if pr.ambulatoire else f'hospitalisation {pr.nuits_post_op} nuit(s)'}"
                       f", score d'urgence {pr.score_urgence}/10. Valeurs reportées ci-dessous.")
    est = st.session_state.get("estim_urg", {})

    with st.form("urgence"):
        gravite = st.radio("Gravité", list(S.GRAVITES), format_func=S.LIBELLES_GRAVITE.get, horizontal=True, index=1)
        c1, c2, c3, c4 = st.columns(4)
        prat = c1.selectbox("Chirurgien qui a vu le patient", praticiens, format_func=lambda x: f"Dr {x}",
                            index=praticiens.index(est.get("prat") or u.get("praticien"))
                            if (est.get("prat") or u.get("praticien")) in praticiens else 0,
                            help="Il pourra être opéré par ce chirurgien, un confrère de même spécialité ou le "
                                 "chirurgien d'urgence (plages URGENCES).")
        duree = c2.number_input("Durée estimée (min)", 15, 480, int(est.get("duree", 60)), step=5)
        amb = c3.radio("Prise en charge", [False, True], index=1 if est.get("amb") else 0,
                       format_func=lambda x: "Ambulatoire" if x else "Hospitalisation")
        post = c4.number_input("Nuits après", 0, 30, int(est.get("post", 2)))
        diag = st.text_input("Motif (facultatif, sans donnée identifiante)", value=est.get("interv", ""),
                             placeholder="ex. fracture col du fémur")
        ok = st.form_submit_button("Déclarer l'urgence au système multi-agent", type="primary", width="stretch")
    if ok:
        numero = 1 + sum(e["type"] == "urgence" for e in DB.lister_evenements())
        p = S.patient_urgent(numero, prat, int(duree), ambulatoire=amb, nuits_post_op=0 if amb else int(post),
                             diagnostic=est.get("cim", ""), type_intervention=diag.strip(), age=int(est.get("age", 40)))
        code = f"URG-{numero:03d}"
        sim2 = C.appliquer(
            lambda: DB.ajouter_evenement(maintenant, "urgence", {"patient": S.patient_vers_dict(p), "gravite": gravite},
                                         u["login"]),
            categorie="Urgence", action="Déclaration d'urgence", patient=code,
            detail=(f"{S.LIBELLES_GRAVITE[gravite]} · vue par Dr {prat} · {int(duree)} min · "
                    f"{'ambulatoire' if amb else f'hospitalisation {int(post)} nuit(s)'}"),
            motif=diag.strip() or "non renseigné")
        st.session_state.pop("estim_urg", None)
        d = next((x for x in reversed(sim2.decisions()) if x.get("patient") == p.id), None)
        delai = S.GRAVITES[gravite].delai_max_min
        if d and d["type"] == "urgence":
            DB.historiser(C.SYSTEME, "automatique", "Urgence",
                          "Prise en charge dans le délai" if d["dans_delai"] else "Prise en charge HORS DÉLAI",
                          patient=code, heure_metier=maintenant,
                          detail=(f"{sim2.modele.salles[d['salle']].nom_affiche}, {C.jour_long(d['debut'].date())} "
                                  f"{d['debut']:%H:%M}, {S.nom_chirurgien(d['chirurgien'])} · attente "
                                  f"{d['attente_min']:.0f} min (délai maximal {delai} min)"),
                          motif=("Programme sans place : confiée au planning de garde (équipe de garde prévenue)"
                                 if d.get("garde") else
                                 f"Meilleure des {d['nb_propositions']} propositions des salles (coût minimal)"))
        else:
            DB.historiser(C.SYSTEME, "automatique", "Urgence", "Aucun créneau dans le délai", patient=code,
                          heure_metier=maintenant, detail=f"délai maximal {delai} min",
                          motif="Transfert vers un autre établissement à décider par le médecin régulateur")
        if d and d["type"] == "urgence":
            st.session_state["flash_urgence"] = ("ok" if d["dans_delai"] else "attention", (
                f"URG-{numero:03d} : programmé(e) avec {S.nom_chirurgien(d['chirurgien'])} en "
                f"{sim2.modele.salles[d['salle']].nom_affiche} à {d['debut']:%H:%M} le {C.jour_long(d['debut'].date())} "
                f"(attente {d['attente_min']:.0f} min, {'dans' if d['dans_delai'] else 'HORS'} délai"
                + (", programme sans place : planning de garde)." if d.get("garde")
                   else f", {d['nb_propositions']} propositions comparées).")))
        else:
            st.session_state["flash_urgence"] = ("attention", f"URG-{numero:03d} : aucun créneau du planning ne convient.")
        st.rerun()


# =============================================================================
# Suivi des urgences : prise en charge et patients décalés par chacune
# =============================================================================

def _suivi() -> None:
    urgences = C.consequences_urgences()
    if not urgences:
        st.info("Aucune urgence déclarée sur l'horizon du programme.")
        return
    for u in urgences:
        pec, deplaces = u["prise_en_charge"], u["deplaces"]
        if not u["survenue"]:
            etat = C.badge("à venir (horloge)", "")
        elif pec is None:
            etat = C.badge("aucun créneau dans le délai", "rouge")
        else:
            etat = C.badge("dans le délai" if pec["dans_delai"] else "HORS DÉLAI", "vert" if pec["dans_delai"] else "rouge")
            if pec.get("garde"):
                etat += " " + C.badge("planning de garde", "ambre")
        with st.container(border=True):
            st.markdown(f"**{u['code']}** · {S.LIBELLES_GRAVITE.get(u['gravite'], u['gravite'])} · déclarée le "
                        f"{C.jour_long(u['heure'].date()).lower()} à {u['heure']:%H:%M} par {u['auteur']} &nbsp;{etat}",
                        unsafe_allow_html=True)
            if pec:
                st.markdown(f"<div class='petit'>Prise en charge : {pec['lieu']} · attente {pec['attente_min']:.0f} min"
                            + (f" (délai maximal {pec['delai_max']} min)" if pec["delai_max"] else "") + "</div>",
                            unsafe_allow_html=True)
            if deplaces:
                st.dataframe(pd.DataFrame(deplaces), hide_index=True, width="stretch")
            elif u["survenue"]:
                st.caption("Aucun patient décalé.")
    st.caption("Patients déplacés par chaque urgence au moment de son insertion. Un même patient peut avoir été "
               "décalé par plusieurs urgences successives.")


# =============================================================================
# Incident logistique
# =============================================================================

def _logistique(sim: S.Simulation) -> None:
    u = C.utilisateur()
    maintenant = C.maintenant()
    pannes = sim.pannes()
    st.markdown("Le **monte-lit** permet de monter les patients hospitalisés au bloc (étage 1) depuis les chambres "
                "(étage 2) et les urgences (rez-de-chaussée). En cas de panne, les salles réordonnent leur programme "
                "(ambulatoires d'abord), décalent ou déprogramment ; les opérés sont retenus en salle de réveil.")
    c1, c2 = st.columns(2)
    with c1.form("panne"):
        st.markdown("**Déclarer une panne**")
        asc = st.selectbox("Ascenseur", list(S.ASCENSEURS), format_func=S.ASCENSEURS.get)
        fin = st.time_input("Retour en service estimé", value=(maintenant + timedelta(hours=3)).time(), step=900)
        ok = st.form_submit_button("Déclarer la panne", type="primary")
    if ok:
        fin_dt = datetime.combine(maintenant.date(), fin)
        if fin_dt <= maintenant:
            st.error("L'heure de retour doit être postérieure à l'heure courante.")
        else:
            typ = "prolongation" if asc in pannes else "panne"
            C.appliquer(lambda: DB.ajouter_evenement(maintenant, typ, {"ascenseur": asc, "fin_estimee": fin_dt.isoformat()},
                                                     u["login"]),
                        categorie="Logistique", action=f"Déclaration {typ} monte-lit",
                        detail=f"{S.ASCENSEURS[asc]}, retour estimé {fin:%H:%M}", motif="Incident logistique")
            st.session_state["flash_urgence"] = ("ok", f"{S.ASCENSEURS[asc]} : {typ} enregistrée jusqu'à {fin:%H:%M}.")
            st.rerun()
    with c2.container(border=True):
        st.markdown("**Remise en service**")
        if not pannes:
            st.caption("Aucune panne en cours.")
        for asc_id, (deb, f) in pannes.items():
            st.write(f"{S.ASCENSEURS.get(asc_id, asc_id)} — en panne depuis {deb:%H:%M} (estimé {f:%H:%M})")
            if st.button(f"Déclarer {asc_id} réparé", key=f"rep_{asc_id}"):
                C.appliquer(lambda: DB.ajouter_evenement(maintenant, "fin_panne", {"ascenseur": asc_id}, u["login"]),
                            categorie="Logistique", action="Remise en service monte-lit",
                            detail=S.ASCENSEURS.get(asc_id, asc_id), motif="Fin d'incident logistique")
                st.session_state["flash_urgence"] = ("ok", f"{asc_id} remis en service : le SMA tente de ré-avancer "
                                                           "les patients décalés.")
                st.rerun()


# =============================================================================
# Absence d'un chirurgien
# =============================================================================

MOTIFS_ABSENCE = ["Vacances", "Congrès / formation", "Maladie", "Autre"]


def _absences(sim: S.Simulation, noms, praticien: str | None = None) -> None:
    """`praticien` : compte chirurgien -> il ne voit, ne déclare et ne modifie que SES absences."""
    u = C.utilisateur()
    maintenant = C.maintenant()
    aujourd = maintenant.date()
    if msg := st.session_state.pop("flash_absence", None):
        st.success(msg)
    st.markdown("Pendant l'absence, les vacations du chirurgien sont **fermées**. Ses patients sont replacés aussitôt "
                "(au plus tôt dans 2 jours, pour pouvoir les prévenir) : chez un **confrère** seulement s'ils l'ont "
                "accepté en consultation, sinon dans les **vacations de leur chirurgien après son retour**. Les urgences "
                "repassent par l'appel d'offres avec leur délai. Une alerte signale tout patient prioritaire repoussé "
                "de plus de 3 jours. Déclarez les absences prévues le plus tôt possible.")
    liste = sorted(C.absences(), key=lambda a: a["du_d"])
    if praticien:
        liste = [a for a in liste if a["praticien"] == praticien]
    actives = [a for a in liste if a["au_d"] >= aujourd]
    decisions = [d for d in sim.decisions() if d["type"] == "absence"]
    if actives:
        st.markdown("**Mes absences en cours et à venir**" if praticien else "**Absences en cours et à venir**")
        st.dataframe(pd.DataFrame([{
            "Chirurgien": f"Dr {a['praticien']}", "Du": C.jour_long(a["du_d"]), "Au": C.jour_long(a["au_d"]),
            "Motif": a.get("motif", "") + (f" — {a['precision']}" if a.get("precision") else ""),
            "Patients replacés": next((d["patients_touches"] for d in decisions
                                       if d["heure"] == a["heure"] and S.code_chirurgien(d["chirurgien"]) == a["praticien"]), "—"),
            "Déclarée par": f"{a['auteur']} le {a['heure']:%d/%m %H:%M}"} for a in actives]),
            hide_index=True, width="stretch")
    else:
        st.caption("Aucune absence en cours ou à venir.")

    with st.form("absence"):
        st.markdown("**Déclarer une absence**")
        c1, c2, c3, c4 = st.columns(4)
        if praticien:
            c1.text_input("Chirurgien", value=f"Dr {praticien}", disabled=True)
            prat = praticien
        else:
            prat = c1.selectbox("Chirurgien", P.praticiens_v28(), format_func=lambda x: f"Dr {x}")
        du = c2.date_input("Du", value=aujourd + timedelta(days=7), min_value=aujourd, format="DD/MM/YYYY")
        au = c3.date_input("Au (inclus)", value=aujourd + timedelta(days=11), min_value=aujourd, format="DD/MM/YYYY")
        motif = c4.selectbox("Motif", MOTIFS_ABSENCE)
        precision = st.text_input("Précision (facultatif)", placeholder="ex. congrès SOFCOT")
        ok = st.form_submit_button("Déclarer l'absence", type="primary")
    if ok:
        if au < du:
            st.error("La date de fin doit suivre la date de début.")
        elif any(a["praticien"] == prat and a["du_d"] <= au and du <= a["au_d"] for a in liste):
            st.error(f"Le Dr {prat} a déjà une absence déclarée qui chevauche cette période : modifiez-la plutôt.")
        else:
            contenu = {"praticien": prat, "du": du.isoformat(), "au": au.isoformat(), "motif": motif,
                       "precision": precision.strip()}
            _enregistrer_absence(lambda: DB.ajouter_evenement(maintenant, "absence", contenu, u["login"]),
                                 "Déclaration d'absence", prat, du, au, motif)

    if actives:
        with st.expander("Modifier ou annuler une absence (retour anticipé, prolongation, erreur de saisie)"):
            a = st.selectbox("Absence", actives, format_func=lambda a: f"Dr {a['praticien']} du {a['du_d']:%d/%m} "
                                                                        f"au {a['au_d']:%d/%m} ({a.get('motif', '')})")
            with st.form("modif_absence", border=False):
                nouvel_au = st.date_input("Nouvelle date de retour (dernier jour d'absence)", value=a["au_d"],
                                          min_value=a["du_d"], format="DD/MM/YYYY")
                justif = st.text_input("Motif de la modification (obligatoire, tracé)")
                c1, c2 = st.columns(2)
                modifier = c1.form_submit_button("Modifier la date de retour")
                annuler = c2.form_submit_button("Annuler cette absence")
            if (modifier or annuler) and not justif.strip():
                st.error("Indiquez le motif de la modification.")
            elif modifier or annuler:
                contenu = {k: a[k] for k in ("praticien", "du", "au", "motif", "precision") if k in a}

                def changer():
                    DB.supprimer_evenement(a["id"])
                    if modifier:            # même heure de déclaration : la période est simplement corrigée
                        DB.ajouter_evenement(a["heure"], "absence", {**contenu, "au": nouvel_au.isoformat()}, a["auteur"])

                _enregistrer_absence(changer, "Modification d'absence" if modifier else "Annulation d'absence",
                                     a["praticien"], a["du_d"], nouvel_au if modifier else a["au_d"], justif.strip())


def _enregistrer_absence(modification, action: str, prat: str, du, au, motif: str) -> None:
    sim2 = C.appliquer(modification, categorie="Programme", action=action, detail=f"Dr {prat} du {du:%d/%m/%Y} au {au:%d/%m/%Y}",
                       motif=motif)
    d = next((x for x in reversed(sim2.decisions()) if x["type"] == "absence"
              and S.code_chirurgien(x["chirurgien"]) == prat), None) if sim2 else None
    alertes = [a for a in (sim2.alertes() if sim2 else []) if f"Absence du Dr {prat}" in a]
    st.session_state["flash_absence"] = (f"{action} : Dr {prat} du {du:%d/%m} au {au:%d/%m}"
                                         + (f" — {d['patients_touches']} patient(s) replacé(s)" if d and action.startswith("Déclaration") else "")
                                         + (f", {len(alertes)} alerte(s) à traiter (bandeau en haut de page)" if alertes else "") + ".")
    st.rerun()


# =============================================================================
# Fil des décisions et messages
# =============================================================================

def _fil(sim: S.Simulation, noms) -> None:
    jours = sorted({h.date() for h, _ in sim.recit})
    if not sim.recit:
        st.info("Aucun événement traité pour l'instant : déclarez une urgence, un incident, ou inscrivez un patient "
                "depuis l'onglet Consultation.")
        return
    jour = st.selectbox("Jour", jours, index=len(jours) - 1, format_func=C.jour_long, key="jour_fil")
    texte = "\n".join(C.lisible(l, noms) for h, l in sim.recit if h.date() == jour)
    st.markdown(f"<div class='recit'>{texte.replace('<', '&lt;')}</div>", unsafe_allow_html=True)
    dec = [d for d in sim.decisions() if d["heure"].date() == jour]
    if dec:
        st.markdown("**Décisions**")
        st.dataframe(pd.DataFrame([{"Heure": d["heure"].strftime("%H:%M"), "Type": d["type"],
                                    "Patient": noms.get(d.get("patient"), "") if d.get("patient") else "",
                                    "Salle": d.get("salle"), "Coût": round(d["cout"]) if "cout" in d else None,
                                    "Détail": C.lisible(d.get("plan", ""), noms)} for d in dec]),
                     hide_index=True, width="stretch")
    if C.est("regulation", "admin"):
        with st.expander("Événements enregistrés (rejoués par le SMA)"):
            evts = DB.lister_evenements()
            st.dataframe(pd.DataFrame([{"#": e["id"], "Heure": e["heure"].strftime("%d/%m %H:%M"), "Type": e["type"],
                                        "Auteur": e["auteur"]} for e in evts]), hide_index=True, width="stretch")
            if evts:
                eid = st.selectbox("Annuler la saisie d'un événement (erreur de saisie)", [e["id"] for e in evts],
                                   format_func=lambda i: f"#{i}")
                with st.form("form_sup_evt", border=False):
                    motif = st.text_input("Motif (obligatoire, tracé)")
                    ok_e = st.form_submit_button("Supprimer cet événement")
                if ok_e and not motif.strip():
                    st.error("Indiquez le motif de la suppression.")
                elif ok_e:
                    e = next(x for x in evts if x["id"] == eid)
                    C.appliquer(lambda: DB.supprimer_evenement(eid), categorie="Programme",
                                action="Suppression d'un événement", motif=motif.strip(),
                                detail=f"#{eid} {e['type']} du {e['heure']:%d/%m %H:%M} saisi par {e['auteur']}")
                    st.rerun()
    if sim.ignores:
        st.caption(f"{len(sim.ignores)} événement(s) hors de l'horizon du programme ou postérieur(s) à l'heure "
                   "courante non rejoué(s).")


def _messages(sim: S.Simulation, noms) -> None:
    j = sim.modele.journal
    st.caption(f"{len(j)} messages FIPA-ACL échangés (protocole Contract Net : CFP → PROPOSE / REFUSE → "
               "ACCEPT / REJECT_PROPOSAL ; vérifications REQUEST → AGREE / REFUSE ; INFORM).")
    if not j:
        return
    convs = sorted({m.conversation for m in j if m.conversation})
    conv = st.selectbox("Conversation", ["(toutes)"] + convs, index=len(convs))
    lignes = [{"Heure": m.heure.strftime("%d/%m %H:%M") if m.heure else "", "Conv.": m.conversation,
               "De": m.emetteur, "À": m.destinataire, "Performatif": m.performatif, "Sujet": m.sujet,
               "Résumé": C.lisible(m.resume, noms)} for m in j if conv == "(toutes)" or m.conversation == conv]
    st.dataframe(pd.DataFrame(lignes[-800:]), hide_index=True, width="stretch", height=420)
