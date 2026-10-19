# -*- coding: utf-8 -*-
"""Onglet TABLEAU DE BORD (administrateur) : situation du bloc et de l'hébergement en temps réel."""
from __future__ import annotations

from datetime import date, datetime
from html import escape

import streamlit as st

from orchestre import sma_service as S
from vues import commun as C
from vues import graphiques as G

SEUILS = ((90, "Saturé", "rouge"), (75, "Tendu", "ambre"), (0, "Normal", "vert"))


def _niveau(pct: float) -> tuple[str, str]:
    return next((lib, coul) for seuil, lib, coul in SEUILS if pct >= seuil)


def _pct(num: float, den: float) -> float:
    return 100 * num / den if den else 0.0


def _h(minutes: float) -> str:
    return f"{minutes / 60:.1f} h".replace(".", ",")


def _minutes(debut: datetime, fin: datetime) -> float:
    return max(0.0, (fin - debut).total_seconds() / 60)


def occupation_bloc(sim: S.Simulation, jour: date) -> dict[int, tuple[float, float]]:
    """Par salle : (minutes ouvertes au planning, minutes programmées) pour la journée."""
    res = {sid: [0.0, 0.0] for sid in sim.modele.salles}
    for f in sim.fenetres_du_jour(jour):
        res[f.salle_id][0] += _minutes(f.debut, f.fin)
    for it in sim.modele.interventions():             # salles du bloc uniquement (pas la salle de garde)
        if it.debut.date() == jour:
            res[it.salle_id][1] += it.patient.duree_bloc
    return {sid: (o, p) for sid, (o, p) in res.items()}


def afficher() -> None:
    sim = C.simulation()
    now = C.maintenant()
    jour = now.date()
    C.entete("Tableau de bord", f"Situation au {C.jour_long(jour).lower()} à {now:%H:%M}")
    if sim is None:
        st.info("Le programme opératoire n'est pas encore calculé.")
        return
    noms = C.noms_patients(sim)
    m = sim.modele
    b = m.bilan()
    occ = sim.occupation(jour)
    bloc = occupation_bloc(sim, jour)
    ouvert, programme = sum(o for o, _ in bloc.values()), sum(p for _, p in bloc.values())
    du_jour = sorted((it for it in sim.interventions() if it.debut.date() == jour), key=lambda it: it.debut)
    en_cours = [it for it in du_jour if it.debut <= now < it.fin]
    salles_ouvertes = {f.salle_id for f in sim.fenetres_du_jour(jour) if f.debut <= now < f.fin}

    pct_bloc = _pct(programme, ouvert)
    pct_lits = _pct(occ["lits"], occ["cap_lits"])
    pct_places = _pct(occ["places"], occ["cap_places"])

    # ---------------------------------------------------------------- en ce moment
    st.markdown("#### En ce moment")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Bloc occupé", f"{pct_bloc:.0f} %", f"{_h(programme)} / {_h(ouvert)}",
              delta_color="off", delta_arrow="off", help="Durée programmée rapportée à la durée des vacations du jour.")
    c2.metric("Salles actives", f"{len({it.salle_id for it in en_cours})} / {len(m.salles)}",
              f"{len(salles_ouvertes)} ouverte(s)", delta_color="off", delta_arrow="off")
    c3.metric("Lits occupés", f"{occ['lits']} / {occ['cap_lits']}",
              f"{max(0, occ['cap_lits'] - occ['lits'])} libres · +{occ['reserve']} réserve",
              delta_color="off", delta_arrow="off")
    c4.metric("Places ambulatoire", f"{occ['places']} / {occ['cap_places']}",
              f"{max(0, occ['cap_places'] - occ['places'])} libre(s)", delta_color="off", delta_arrow="off")
    c5.metric("Liste d'attente", b["patients_en_liste_attente"], "sans créneau",
              delta_color="off", delta_arrow="off")
    st.markdown(" ".join(C.badge(f"{lib} : {_niveau(p)[0]} ({p:.0f} %)", _niveau(p)[1])
                         for lib, p in (("Bloc", pct_bloc), ("Lits", pct_lits), ("Ambulatoire", pct_places))),
                unsafe_allow_html=True)
    st.caption("Seuils : normal < 75 % · tendu de 75 à 90 % · saturé ≥ 90 %.")

    for a in b["alertes"][-3:]:
        st.error(C.lisible(a, noms))
    for asc, (deb, fin) in sim.pannes().items():
        if deb <= now < fin:
            st.warning(f"{S.ASCENSEURS.get(asc, asc)} en panne depuis {deb:%H:%M}, retour estimé {fin:%H:%M}.")

    # ---------------------------------------------------------------- salles
    st.markdown("#### Salles d'opération")
    st.markdown(_tableau_salles(sim, bloc, du_jour, salles_ouvertes, noms, now), unsafe_allow_html=True)

    # ---------------------------------------------------------------- activité
    st.markdown("#### Activité du jour")
    urg = [it for it in du_jour if it.urgence]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Interventions prévues", len(du_jour))
    c2.metric("Terminées", sum(it.fin <= now for it in du_jour))
    c3.metric("En cours", len(en_cours))
    c4.metric("À venir", sum(it.debut > now for it in du_jour))
    c5.metric("Urgences du jour", len(urg), f"{sum(not it.patient.ambulatoire for it in urg)} hospitalisée(s)",
              delta_color="off", delta_arrow="off")

    # ---------------------------------------------------------------- tendances
    st.markdown("#### Tendances sur l'horizon du programme")
    jours = [j for j in sim.jours_tendances() if j.weekday() < 5]
    taux = {}
    for j in jours:
        ob = occupation_bloc(sim, j).values()
        taux[j] = _pct(sum(p for _, p in ob), sum(o for o, _ in ob))
    g1, g2 = st.columns(2)
    with g1.container(border=True):
        st.markdown("**Taux d'occupation du bloc par jour**")
        st.plotly_chart(G.taux_bloc(taux, jour), width="stretch", config={"displayModeBar": False})
    with g2.container(border=True):
        st.markdown("**Lits et places ambulatoires occupés**")
        st.plotly_chart(G.occupation_hebergement(sim), width="stretch", config={"displayModeBar": False})

    # ---------------------------------------------------------------- qualité de service
    st.markdown("#### Perturbations et qualité de service")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Urgences insérées", b["urgences_inserees"], f"{b['urgences_dans_delai']} dans le délai",
              delta_color="off", delta_arrow="off")
    c2.metric("Attente urgences", f"{b['attente_moyenne_urgence_min']:.0f} min")
    c3.metric("Patients décalés", b["patients_decales"], f"{b['minutes_de_decalage_cumulees']} min cumulées",
              delta_color="off", delta_arrow="off")
    c4.metric("Reportés", b["patients_reportes_autre_jour"], help="Patients reportés à un autre jour.")
    c5.metric("Repris (confrère)", b["patients_repris_par_un_confrere"])

def _tableau_salles(sim: S.Simulation, bloc: dict, du_jour: list, ouvertes: set[int], noms: dict,
                    now: datetime) -> str:
    lignes = []
    for salle in sim.salles(now.date()):
        sid = salle.salle_id
        its = [it for it in du_jour if it.salle_id == sid]
        cours = next((it for it in its if it.debut <= now < it.fin), None)
        suivante = next((it for it in its if it.debut > now), None)
        if cours:
            statut = C.badge("urgence en cours", "rouge") if cours.urgence else C.badge("en intervention", "bleu")
            detail = (f"{escape(noms.get(cours.pid, str(cours.pid)))} · {S.nom_chirurgien(cours.chirurgien_id)}"
                      f"<small>fin prévue {cours.fin:%H:%M}</small>")
        elif sid in ouvertes:
            statut, detail = C.badge("disponible", "vert"), "—"
        else:
            statut, detail = C.badge("fermée"), "—"
        prochaine = (f"{suivante.debut:%H:%M} · {escape(noms.get(suivante.pid, str(suivante.pid)))}"
                     if suivante else "—")
        o, p = bloc.get(sid, (0, 0))
        pct = _pct(p, o)
        jauge = (f"<div class='jauge'><span style='width:{min(pct, 100):.0f}%'></span></div>"
                 f"<small>{pct:.0f} % · {sum(it.fin <= now for it in its)}/{len(its)} terminée(s)</small>"
                 if o else "<small>pas de vacation</small>")
        lignes.append(f"<tr><td class='salle'>{escape(salle.nom_affiche)}</td><td>{statut}</td><td>{detail}</td>"
                      f"<td>{prochaine}</td><td>{jauge}</td></tr>")
    return ("<table class='grille tdb'><tr><th>Salle</th><th>Statut</th><th>Intervention en cours</th>"
            "<th>Prochaine</th><th>Occupation du jour</th></tr>" + "".join(lignes) + "</table>")
