# -*- coding: utf-8 -*-
"""Graphiques Plotly (Gantt de la journée, occupation des lits, convergence)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

import plotly.graph_objects as go

from orchestre import sma_service as S

PALETTE = ["#1F5F8B", "#2E8B57", "#7B4FA0", "#B8860B", "#3A8FB7", "#A0522D", "#5F7D2E", "#6A5ACD",
           "#2F6F6F", "#8B5A83"]
ROUGE = "#C62828"


def _ms(td: timedelta) -> float:
    return td.total_seconds() * 1000


def gantt_jour(sim: S.Simulation, jour: date, noms: dict[int, str], moi: Optional[int] = None,
               hauteur_ligne: int = 62, seulement: Optional[int] = None) -> go.Figure:
    """`seulement` : id d'un chirurgien -> n'affiche que ses vacations et ses interventions (confidentialité)."""
    m = sim.modele
    salles = list(m.salles.values())
    fenetres = sim.fenetres_du_jour(jour)
    du_jour = {s.salle_id: s.du_jour(jour) for s in salles}
    if seulement is not None:
        du_jour = {sid: [it for it in its if it.chirurgien_id == seulement] for sid, its in du_jour.items()}
        siennes = {it.fenetre_id for its in du_jour.values() for it in its}
        fenetres = [f for f in fenetres if f.chirurgien_id == seulement or (f.urgence and f.id in siennes)]
        utilisees = {f.salle_id for f in fenetres} | {sid for sid, its in du_jour.items() if its}
        salles = [s for s in salles if s.salle_id in utilisees] or salles
    ordre = [s.nom_affiche for s in salles]
    chirs = sorted({f.chirurgien_id for f in fenetres if not f.urgence}
                   | {it.chirurgien_id for its in du_jour.values() for it in its})
    couleur = {c: PALETTE[k % len(PALETTE)] for k, c in enumerate(chirs)}
    fig = go.Figure()

    # créneaux du planning (vacations / plages d'urgence)
    for f in fenetres:
        nom = m.salles[f.salle_id].nom_affiche
        lib = "Plage URGENCES" if f.urgence else f"Vacation {S.code_chirurgien(f.chirurgien_id)}"
        fig.add_trace(go.Bar(
            y=[nom], x=[_ms(f.fin - f.debut)], base=[f.debut], orientation="h", width=0.86,
            marker=dict(color="rgba(198,40,40,0.06)" if f.urgence else "rgba(31,95,139,0.06)",
                        line=dict(color=ROUGE if f.urgence else couleur.get(f.chirurgien_id, "#888"), width=1.2)),
            hovertemplate=f"{lib}<br>{f.debut:%H:%M}–{f.fin:%H:%M}<extra></extra>", showlegend=False))
        fig.add_annotation(x=f.debut + timedelta(minutes=4), y=nom, text=lib, showarrow=False, xanchor="left",
                           yshift=hauteur_ligne * 0.36, font=dict(size=10, color="#5B6770"))

    # interventions
    vus = set()
    for s in salles:
        for it in du_jour[s.salle_id]:
            urg = it.urgence
            c = ROUGE if urg else couleur.get(it.chirurgien_id, "#888")
            leg = "Urgence" if urg else f"Dr {S.code_chirurgien(it.chirurgien_id)}"
            d = int((it.debut - it.debut_initial).total_seconds() // 60)
            etat = []
            if not urg and it.debut_initial.date() != it.debut.date():
                etat.append(f"reporté du {it.debut_initial:%d/%m}")
            elif d:
                etat.append(f"{'décalé +' if d > 0 else 'avancé '}{abs(d)} min")
            if it.chirurgien_id != it.chirurgien_initial:
                etat.append(f"repris (au lieu de {S.code_chirurgien(it.chirurgien_initial)})")
            p = it.patient
            txt = (f"<b>{noms.get(it.pid, it.pid)}</b><br>{it.debut:%H:%M}–{it.fin:%H:%M} ({p.duree_bloc} min)"
                   f"<br>Dr {S.code_chirurgien(it.chirurgien_id)} · priorité {p.priorite}"
                   f"<br>{'ambulatoire' if p.ambulatoire else f'hospitalisé ({p.nuits_post_op} nuit(s) post-op)'}"
                   + (f"<br>{', '.join(etat)}" if etat else ""))
            fig.add_trace(go.Bar(
                y=[s.nom_affiche], x=[_ms(it.duree)], base=[it.debut], orientation="h", width=0.5,
                marker=dict(color=c, pattern=dict(shape="/" if p.ambulatoire else "", fgcolor="rgba(255,255,255,0.45)", fillmode="overlay"),
                            line=dict(color="#0B2A40" if (moi and it.chirurgien_id == moi) else "white",
                                      width=2.5 if (moi and it.chirurgien_id == moi) else 1)),
                text=noms.get(it.pid, str(it.pid)), textposition="inside", insidetextanchor="middle",
                textfont=dict(color="white", size=10), hovertemplate=txt + "<extra></extra>",
                name=leg, legendgroup=leg, showlegend=leg not in vus))
            vus.add(leg)

    # pannes de monte-lit et heure courante
    for a, b in sim.pannes().values():
        a2, b2 = max(a, datetime.combine(jour, time(7))), min(b, datetime.combine(jour, time(19)))
        if a2 < b2:
            fig.add_vrect(x0=a2, x1=b2, fillcolor="#9E9E9E", opacity=0.18, line_width=0,
                          annotation_text="monte-lit en panne", annotation_position="top left")
    if sim.maintenant.date() == jour:
        fig.add_vline(x=sim.maintenant, line=dict(color="#C62828", width=2, dash="dot"))
        fig.add_annotation(x=sim.maintenant, y=1.02, yref="paper", text=f"maintenant {sim.maintenant:%H:%M}",
                           showarrow=False, font=dict(color="#C62828", size=11))

    fig.update_layout(
        barmode="overlay", height=90 + hauteur_ligne * len(salles), margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(type="date", range=[datetime.combine(jour, time(7, 30)), datetime.combine(jour, time(18, 0))],
                   tickformat="%Hh", dtick=3600 * 1000, gridcolor="#E6EBF0"),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(ordre))),
        plot_bgcolor="white", legend=dict(orientation="h", y=-0.12, font=dict(size=11)),
        hoverlabel=dict(bgcolor="white", font_size=12))
    return fig


def occupation_hebergement(sim: S.Simulation) -> go.Figure:
    lits, places = sim.modele.hebergement.occupation()
    h = sim.modele.instance2.hebergement
    jours = sim.jours()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=jours, y=[lits.get(j, 0) for j in jours], name="Lits occupés", marker_color="#1F5F8B"))
    fig.add_trace(go.Bar(x=jours, y=[places.get(j, 0) for j in jours], name="Places ambulatoires", marker_color="#00897B"))
    fig.add_hline(y=h.cap_lits, line=dict(color="#1F5F8B", dash="dash"),
                  annotation_text=f"capacité lits ({h.cap_lits} + {h.reserve_lits} de réserve)")
    fig.add_hline(y=h.cap_places, line=dict(color="#00897B", dash="dot"),
                  annotation_text=f"capacité ambulatoire ({h.cap_places})", annotation_position="bottom right")
    if jours and jours[0] <= sim.maintenant.date() <= jours[-1]:
        fig.add_vline(x=datetime.combine(sim.maintenant.date(), time(0)), line=dict(color="#C62828", dash="dot"))
    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=20, b=10), plot_bgcolor="white",
                      legend=dict(orientation="h", y=-0.2), yaxis=dict(gridcolor="#E6EBF0", title="patients"),
                      xaxis=dict(tickformat="%a %d/%m"))
    return fig


def convergence(series: dict[str, list[tuple[float, float]]], titre: str = "") -> go.Figure:
    fig = go.Figure()
    for k, (nom, pts) in enumerate(series.items()):
        if pts:
            fig.add_trace(go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines", name=nom,
                                     line=dict(shape="hv", width=2, color=PALETTE[k % len(PALETTE)])))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30 if titre else 10, b=10), plot_bgcolor="white",
                      title=titre or None, xaxis=dict(title="temps de calcul (s)", gridcolor="#E6EBF0"),
                      yaxis=dict(title="meilleur score (à minimiser)", gridcolor="#E6EBF0"),
                      legend=dict(orientation="h", y=-0.25))
    return fig
