# -*- coding: utf-8 -*-
"""Onglet ADMINISTRATION : comptes, capacités d'hébergement et horloge de démonstration."""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from orchestre import programme as P
from orchestre import sma_service as S
from orchestre import stockage as DB
from vues import commun as C

import structures_communes as SC


def afficher() -> None:
    if not C.est("admin"):
        st.error("Accès réservé à l'administrateur.")
        return
    C.entete("Administration")
    t1, t_vac, t_cap, t_opt, t2 = st.tabs(["Comptes", "Planning des vacations", "Lits et places",
                                           "Optimisation globale", "Horloge"])
    with t1:
        _comptes()
    with t_vac:
        _planning_vacations()
    with t_cap:
        _capacites()
    with t_opt:
        _optimisation_globale()
    with t2:
        _horloge()


def _capacites() -> None:
    h = C.hebergement()
    if msg := st.session_state.pop("flash_capacites", None):
        st.success(msg)
    st.markdown("Capacités d'hébergement **par jour**, utilisées par le programme opératoire et par le système "
                "multi-agent (acceptation d'une urgence, d'une inscription ou d'un replacement). Les lits de "
                "**réserve** ne sont jamais attribués à la programmation : ils restent libres pour les urgences.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Lits d'hospitalisation", h.lits_disponibles_par_jour)
    c2.metric("dont réserve urgences", h.reserve_lits, f"{h.cap_lits} lits programmables", delta_color="off",
              delta_arrow="off")
    c3.metric("Places ambulatoires", h.places_ambulatoires_par_jour)
    with st.form("form_capacites"):
        c1, c2, c3 = st.columns(3)
        lits = c1.number_input("Lits d'hospitalisation", 1, 500, h.lits_disponibles_par_jour)
        reserve = c2.number_input("Réserve d'urgence (lits)", 0, 500, h.reserve_lits)
        places = c3.number_input("Places ambulatoires", 0, 500, h.places_ambulatoires_par_jour)
        cfg = C.config_programme() or {}
        modes = list(P.MODES_HYBRIDES)
        recalculer = st.checkbox("Recalculer aussi le programme opératoire avec ces capacités",
                                 help="Sans recalcul, le programme déjà construit est conservé : les nouvelles "
                                      "capacités s'appliquent aux décisions du système multi-agent (urgences, "
                                      "inscriptions, replacements). Avec recalcul, l'hybridation AGS + RS + Tabou "
                                      "réaffecte les patients de démonstration en respectant les nouvelles capacités.")
        mode = st.selectbox("Méthode de calcul du programme (si recalcul)", modes, format_func=P.MODES_HYBRIDES.get,
                            index=modes.index(P.MODE_PROGRAMME),
                            help=f"Toutes les méthodes (hybrides et références RS / Tabou / AGS seuls) tournent "
                                 f"{P.BUDGET_OPTIMISATION_S:.0f} s.")
        motif = st.text_input("Motif (obligatoire, tracé)", placeholder="ex. capacités réelles du service")
        ok = st.form_submit_button("Enregistrer", type="primary")
    if not ok:
        return
    if not motif.strip():
        st.error("Indiquez le motif de la modification.")
        return
    if reserve >= lits:
        st.error("La réserve d'urgence doit être inférieure au nombre de lits.")
        return
    nouveau = SC.ParametresHebergement(int(lits), int(places), int(reserve))
    if nouveau == h and not recalculer:
        st.info("Aucune modification.")
        return
    detail = ((f"lits {h.lits_disponibles_par_jour} → {nouveau.lits_disponibles_par_jour}, réserve {h.reserve_lits} → "
               f"{nouveau.reserve_lits}, places {h.places_ambulatoires_par_jour} → {nouveau.places_ambulatoires_par_jour}"
               if nouveau != h else "capacités inchangées")
              + (f" · programme recalculé ({P.MODES_HYBRIDES[mode]})" if recalculer else ""))

    def modifier():
        DB.ecrire_parametre("hebergement", {"lits_disponibles_par_jour": nouveau.lits_disponibles_par_jour,
                                            "places_ambulatoires_par_jour": nouveau.places_ambulatoires_par_jour,
                                            "reserve_lits": nouveau.reserve_lits})
        if recalculer:
            prog = P.calculer_programme(date.fromisoformat(cfg["lundi"]) if cfg else C.maintenant().date(),
                                        mode, P.BUDGET_OPTIMISATION_S, hebergement=nouveau)
            C.enregistrer_programme(prog, C.utilisateur()["login"])

    with st.spinner("Recalcul du programme opératoire…" if recalculer else "Enregistrement…"):
        C.appliquer(modifier, categorie="Programme", action="Modification des capacités d'hébergement",
                    detail=detail, motif=motif.strip())
    validite = (C.config_programme() or {}).get("validation") or {}
    st.session_state["flash_capacites"] = (f"Capacités enregistrées : {detail}."
                                           + ("" if not recalculer or validite.get("faisable", True) else
                                              " ATTENTION : le programme recalculé n'est PAS valide (voir Planning)."))
    st.rerun()


JOURS_SEMAINE = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
TYPES = {"paire": "Paire", "impaire_1": "Impaire A", "impaire_2": "Impaire B"}


def _blocs_vers_lignes(blocs: list) -> pd.DataFrame:
    lignes = [{"Jour": JOURS_SEMAINE[j], "Salle": sal, "Praticien": nom, "Début": deb, "Fin": fin,
               **{lib: t in sem for t, lib in TYPES.items()}} for j, sal, nom, deb, fin, sem in blocs]
    def cle(c: pd.Series) -> pd.Series:
        if c.name == "Jour":
            return c.map({j: k for k, j in enumerate(JOURS_SEMAINE)})
        if c.name == "Début":                                # « 7:45 » avant « 10:00 »
            return c.map(lambda x: tuple(int(v) for v in str(x).split(":")))
        return c

    return pd.DataFrame(lignes).sort_values(["Jour", "Salle", "Début"], key=cle).reset_index(drop=True)


def _lignes_vers_blocs(df: pd.DataFrame) -> list:
    blocs = []
    for _, r in df.iterrows():
        if not str(r.get("Praticien") or "").strip() and not str(r.get("Début") or "").strip():
            continue                                         # ligne vide ajoutée par erreur
        blocs.append([JOURS_SEMAINE.index(r["Jour"]) if r["Jour"] in JOURS_SEMAINE else -1,
                      int(r["Salle"]) if pd.notna(r["Salle"]) else -1, str(r["Praticien"] or "").strip().upper(),
                      str(r["Début"] or "").strip().replace("h", ":"), str(r["Fin"] or "").strip().replace("h", ":"),
                      [t for t, lib in TYPES.items() if bool(r.get(lib))]])
    return blocs


def _planning_vacations() -> None:
    V28 = P.V28
    if msg := st.session_state.pop("flash_vacations", None):
        st.success(msg)
    d = C.planning_vacations()
    cfg = C.config_programme() or {}
    aujourd = C.maintenant().date()
    prochain_lundi = P.lundi_de(aujourd) + timedelta(weeks=1)
    fin_optimise = (date.fromisoformat(cfg["lundi"]) + timedelta(weeks=cfg.get("nb_semaines", P.NB_SEMAINES_HORIZON))
                    if cfg else prochain_lundi)
    st.markdown("Le planning des vacations est **fixe** : il se répète à l'identique toutes les semaines (cycle "
                "semaine paire / impaire A / impaire B). Une modification s'applique **à partir d'un lundi à venir** ; "
                "les semaines précédentes gardent l'ancien planning. Le système multi-agent replace aussitôt les "
                "patients concernés selon le nouveau planning.")
    if d["versions"]:
        st.markdown("**Versions enregistrées**")
        st.dataframe(pd.DataFrame([{"En vigueur à partir du": C.jour_long(date.fromisoformat(v["effet"])),
                                    "Vacations": len(v["blocs"]), "Par": v.get("auteur", ""),
                                    "Motif": v.get("motif", "")} for v in d["versions"]]),
                     hide_index=True, width="stretch")
    else:
        st.caption("Aucune modification : planning d'origine (version 28) sur toutes les semaines.")

    c1, c2 = st.columns([1, 2])
    effet = c1.date_input("À partir du lundi", value=prochain_lundi, min_value=prochain_lundi, format="DD/MM/YYYY",
                          key="effet_vacations")
    effet = P.lundi_de(effet)
    if effet < prochain_lundi:
        effet = prochain_lundi
    c2.markdown(f"<div class='petit'>Modification appliquée à partir du <b>{C.jour_long(effet)}</b>. "
                + ("Cette date tombe dans les semaines déjà optimisées : le programme opératoire sera <b>recalculé</b> "
                   f"(environ {P.BUDGET_OPTIMISATION_S:.0f} s)." if effet < fin_optimise else
                   "Les semaines optimisées ne changent pas : seul le système multi-agent utilise le nouveau planning.")
                + "</div>", unsafe_allow_html=True)
    actuels = V28.blocs_pour(effet)
    suivantes = [v for v in d["versions"] if date.fromisoformat(v["effet"]) > effet]
    if suivantes:
        st.warning(f"Une version plus récente existe déjà (à partir du "
                   f"{C.jour_long(date.fromisoformat(suivantes[0]['effet']))}) : cette modification ne s'appliquera "
                   f"que jusqu'à cette date. Chaque version est un planning complet, en vigueur jusqu'à la suivante.")
    st.caption("Une ligne par plage : jour, salle, code du praticien (ou URGENCE / LIBRE), horaires (ex. 8:00 – 13:00) "
               "et types de semaine où elle a lieu. Une plage qui enjambe 13 h – 13 h 30 est coupée en deux "
               "automatiquement. Ajoutez une ligne en bas du tableau, supprimez-en une en la sélectionnant.")
    with st.form("form_vacations"):
        edite = st.data_editor(
            _blocs_vers_lignes(actuels), num_rows="dynamic", hide_index=True, width="stretch",
            key=f"editeur_vacations_{effet}",
            column_config={
                "Jour": st.column_config.SelectboxColumn(options=JOURS_SEMAINE, required=True),
                "Salle": st.column_config.SelectboxColumn(options=sorted(V28.SALLES), required=True),
                "Praticien": st.column_config.TextColumn(required=True, help="Code du praticien, URGENCE ou LIBRE"),
                "Début": st.column_config.TextColumn(required=True, help="ex. 8:00"),
                "Fin": st.column_config.TextColumn(required=True, help="ex. 13:00"),
                **{lib: st.column_config.CheckboxColumn(default=True) for lib in TYPES.values()}})
        motif = st.text_input("Motif (obligatoire, tracé)", placeholder="ex. nouvelle vacation du Dr XX le jeudi")
        ok = st.form_submit_button("Enregistrer le nouveau planning", type="primary")
    a_supprimer = [v for v in d["versions"] if date.fromisoformat(v["effet"]) >= prochain_lundi]
    if a_supprimer:
        with st.popover("Annuler une version à venir"):
            choix = st.selectbox("Version", a_supprimer,
                                 format_func=lambda v: f"à partir du {C.jour_long(date.fromisoformat(v['effet']))}")
            motif_s = st.text_input("Motif de l'annulation (obligatoire)", key="motif_annul_vac")
            if st.button("Annuler cette version", type="primary"):
                if not motif_s.strip():
                    st.error("Indiquez le motif.")
                else:
                    reste = [v for v in d["versions"] if v is not choix and v["effet"] != choix["effet"]]
                    _appliquer_planning({**d, "versions": reste}, date.fromisoformat(choix["effet"]), fin_optimise,
                                        "Annulation d'une version du planning des vacations",
                                        f"version du {choix['effet']} annulée", motif_s.strip())
    if not ok:
        return
    if not motif.strip():
        st.error("Indiquez le motif de la modification.")
        return
    blocs = _lignes_vers_blocs(edite)
    erreurs = V28.verifier_blocs(blocs) if blocs else ["le planning est vide"]
    if erreurs:
        st.error("Planning non enregistré :\n\n" + "\n".join(f"- {e}" for e in erreurs[:12]))
        return
    if sorted(map(tuple, (b[:5] + [tuple(b[5])] for b in blocs))) == sorted(map(tuple, (list(b[:5]) + [tuple(b[5])] for b in actuels))):
        st.info("Aucune modification par rapport au planning en vigueur à cette date.")
        return
    avant = {b[2] for b in actuels} - {V28.NOM_URGENCE, V28.NOM_LIBRE}
    apres = {b[2] for b in blocs} - {V28.NOM_URGENCE, V28.NOM_LIBRE}
    u = C.utilisateur()
    version = {"effet": effet.isoformat(), "blocs": blocs, "auteur": u["login"], "motif": motif.strip(),
               "cree_le": DB.horodatage()}
    versions = [v for v in d["versions"] if v["effet"] != version["effet"]] + [version]
    detail = (f"à partir du {effet:%d/%m/%Y} : {len(actuels)} → {len(blocs)} plage(s)"
              + (f", praticien(s) ajouté(s) : {', '.join(sorted(apres - avant))}" if apres - avant else "")
              + (f", praticien(s) sans vacation : {', '.join(sorted(avant - apres))}" if avant - apres else ""))
    _appliquer_planning({**d, "versions": sorted(versions, key=lambda v: v["effet"])}, effet, fin_optimise,
                        "Modification du planning des vacations", detail, motif.strip())


def _appliquer_planning(nouveau: dict, effet: date, fin_optimise: date, action: str, detail: str, motif: str) -> None:
    """Enregistre les versions (ids des nouveaux praticiens compris) et recalcule le programme si la date d'effet
    tombe dans les semaines optimisées ; les déplacements de patients qui en découlent sont tracés."""
    V28 = P.V28
    recalcul = effet < fin_optimise

    def modifier():
        ids = V28.definir_versions([(date.fromisoformat(v["effet"]), v["blocs"]) for v in nouveau["versions"]],
                                   nouveau.get("praticiens"))
        DB.ecrire_parametre("planning_vacations", {**nouveau, "praticiens": ids})
        if recalcul:
            cfg = C.config_programme()
            prog = P.calculer_programme(date.fromisoformat(cfg["lundi"]) if cfg else C.maintenant().date(),
                                        P.MODE_PROGRAMME, P.BUDGET_OPTIMISATION_S,
                                        hebergement=C.hebergement())
            C.enregistrer_programme(prog, C.utilisateur()["login"])

    with st.spinner("Recalcul du programme opératoire…" if recalcul else "Enregistrement…"):
        C.appliquer(modifier, categorie="Programme", action=action,
                    detail=detail + (" · programme recalculé" if recalcul else ""), motif=motif)
    st.session_state["flash_vacations"] = f"{action} : {detail}" + (" · programme recalculé." if recalcul else ".")
    st.rerun()


def _optimisation_globale() -> None:
    import metaheuristiques_sma as MS
    if msg := st.session_state.pop("flash_optimisation", None):
        {"ok": st.success, "info": st.info}[msg[0]](msg[1])
    sim = C.simulation()
    if sim is None:
        st.info("Le programme opératoire n'est pas encore calculé.")
        return
    m = sim.modele

    def nb(x: float) -> str:
        return f"{x:,.0f}".replace(",", " ")

    st.markdown("Sur le site, le système multi-agent réagit à chaque aléa par une optimisation **locale** (dans la "
                "salle concernée). Si le programme vous semble trop dégradé, lancez ici une optimisation **globale** : "
                "l'agent Optimisation réaffecte les patients encore déplaçables (toutes les salles, tout l'horizon), "
                "puis les agents Chirurgien et Hébergement valident le plan. Il n'est appliqué que s'il améliore le "
                "score. Les interventions commencées ou qui commencent dans l'heure, les urgences et le planning de "
                "garde ne bougent pas.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score du programme", nb(m.score_programme()['total']),
              help="Coût global à minimiser : décalages, reports, changements de chirurgien, liste d'attente, "
                   "attente des urgences, lits et places.")
    c2.metric("Patients en liste d'attente", len(sim.en_attente()))
    faites = [d for d in sim.decisions() if d["type"] == "reoptimisation"]
    c3.metric("Optimisations globales appliquées", len(faites))
    with st.form("form_optimisation"):
        c1, c2 = st.columns(2)
        methode = c1.selectbox("Méthode", list(MS.MODES), index=list(MS.MODES).index("memetique"),
                               format_func=lambda x: MS.NOMS.get(x, x))
        budget = c2.slider("Temps de calcul (s)", 1, 30, 5)
        motif = st.text_input("Motif (obligatoire, tracé)", placeholder="ex. nombreux patients décalés après les urgences")
        ok = st.form_submit_button("Lancer l'optimisation globale", type="primary")
    if faites:
        st.caption("Dernières : " + " · ".join(f"{d['heure']:%d/%m %H:%M} {MS.NOMS.get(d['methode'], d['methode'])}, "
                                              f"{d['patients_deplaces']} patient(s), gain {nb(d['gain'])}"
                                              for d in faites[-3:]))
    if not ok:
        return
    if not motif.strip():
        st.error("Indiquez le motif de l'optimisation.")
        return
    now = C.maintenant()
    with st.spinner(f"Optimisation globale ({MS.NOMS.get(methode, methode)}, {budget} s)…"):
        contenu, message, scores = S.calculer_reoptimisation(C.programme(), DB.lister_evenements(), now, methode,
                                                             float(budget))
    if contenu is None:
        C.tracer("optimisation globale sans effet", message)
        st.session_state["flash_optimisation"] = ("info", f"Programme inchangé. {message}")
        st.rerun()
    u = C.utilisateur()
    detail = (f"{MS.NOMS.get(methode, methode)}, {budget} s : score {nb(scores['avant'])} → {nb(scores['apres'])}, "
              f"{message}")
    C.appliquer(lambda: DB.ajouter_evenement(now, "reoptimisation", contenu, u["login"]), categorie="Programme",
                action="Optimisation globale du programme", detail=detail, motif=motif.strip())
    st.session_state["flash_optimisation"] = ("ok", f"Optimisation appliquée — {detail}")
    st.rerun()


def _comptes() -> None:
    st.dataframe(pd.DataFrame(DB.lister_utilisateurs()), hide_index=True, width="stretch")
    with st.form("nouveau_compte"):
        st.markdown("**Créer un compte nominatif**")
        c1, c2, c3, c4 = st.columns(4)
        login = c1.text_input("Identifiant")
        nom = c2.text_input("Nom affiché", placeholder="Dr XX")
        role = c3.selectbox("Rôle", list(DB.ROLES), format_func=DB.ROLES.get)
        prat = c4.selectbox("Code praticien (chirurgien)", [""] + P.praticiens_v28())
        ok = st.form_submit_button("Créer (mot de passe provisoire)")
    if ok and login.strip():
        mdp = "Tmp-" + secrets.token_urlsafe(10)
        DB.creer_utilisateur(login.strip(), mdp, role, nom or login, prat, doit_changer=True)
        C.tracer("création de compte", login)
        st.success(f"Compte créé. Mot de passe provisoire à transmettre par un canal sûr : `{mdp}`")
    c1, c2 = st.columns(2)
    cible = c1.selectbox("Compte", [u["login"] for u in DB.lister_utilisateurs()])
    if c2.button("Désactiver / réactiver"):
        u = next(x for x in DB.lister_utilisateurs() if x["login"] == cible)
        DB.activer_utilisateur(cible, not u["actif"])
        C.tracer("activation/désactivation de compte", cible)
        st.rerun()


def _horloge() -> None:
    h = C.horloge()
    st.markdown("En production, l'application suit l'heure réelle. Pour une **démonstration**, figez une heure "
                "simulée et avancez-la pour voir le SMA dérouler la journée (interventions terminées, relance de la "
                "liste d'attente à 7 h, fin de panne estimée…).")
    st.markdown(C.badge("heure réelle" if h.get("mode") != "demo" else f"démonstration : {h['instant']}",
                        "vert" if h.get("mode") != "demo" else "ambre"), unsafe_allow_html=True)
    now = C.maintenant()
    c1, c2, c3 = st.columns(3)
    d = c1.date_input("Date", value=now.date(), format="DD/MM/YYYY")
    t = c2.time_input("Heure", value=now.time(), step=300)
    if c3.button("Fixer l'heure simulée", type="primary"):
        C.regler_horloge(datetime.combine(d, t))
        C.tracer("horloge de démonstration", f"{d} {t}")
        st.rerun()
    b1, b2, b3, b4 = st.columns(4)
    for col, lib, delta in ((b1, "+30 min", timedelta(minutes=30)), (b2, "+2 h", timedelta(hours=2))):
        if col.button(lib, width="stretch"):
            C.regler_horloge(now + delta)
            st.rerun()
    if b3.button("Lendemain 7 h 30", width="stretch"):
        C.regler_horloge(datetime.combine(now.date() + timedelta(days=1), time(7, 30)))
        st.rerun()
    if b4.button("Revenir à l'heure réelle", width="stretch"):
        C.regler_horloge(None)
        st.rerun()
    st.divider()
    with st.popover("Réinitialiser la démonstration"):
        st.write("Supprime tous les événements (inscriptions, urgences, pannes). Les fiches patients sont conservées "
                 "avec le statut « à programmer ».")
        with st.form("form_reinit", border=False):
            motif = st.text_input("Motif (obligatoire, tracé)")
            ok_r = st.form_submit_button("Confirmer", type="primary")
        if ok_r and not motif.strip():
            st.error("Indiquez le motif de la réinitialisation.")
        elif ok_r:
            C.appliquer(DB.vider_evenements, categorie="Programme", action="Réinitialisation de tous les événements",
                        motif=motif.strip())
            st.rerun()
