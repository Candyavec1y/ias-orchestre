# -*- coding: utf-8 -*-
"""Graphiques Plotly (Gantt de la journée, occupation des lits, convergence)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

import plotly.graph_objects as go

from orchestre import sma_service as S

PALETTE = ["#2626F5", "#1E9E6E", "#8A5CF6", "#F29E4C", "#5B7BF9", "#1B9AAA", "#0E0E8C", "#C2569B",
           "#3CCB94", "#7D8CC4"]
ROUGE = "#C62828"
BLEU, MENTHE, GRILLE, NUIT = "#2626F5", "#1E9E6E", "#E3E8FB", "#0B0B45"
POLICE = dict(family="Raleway, sans-serif", color="#17175E")
JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def _jour_court(j: date) -> str:
    return f"{JOURS_COURTS[j.weekday()]} {j:%d/%m}"


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
    # hauteur réelle d'une ligne de salle (zone de tracé = 26 px + hauteur_ligne par salle, cf. update_layout)
    bande = hauteur_ligne + 26 / max(1, len(salles))

    # créneaux du planning (vacations / plages d'urgence) ; le libellé est posé AU-DESSUS du cadre
    for f in fenetres:
        nom = m.salles[f.salle_id].nom_affiche
        lib = "Plage URGENCES" if f.urgence else f"Vacation {S.code_chirurgien(f.chirurgien_id)}"
        fig.add_trace(go.Bar(
            y=[nom], x=[_ms(f.fin - f.debut)], base=[f.debut], orientation="h", width=0.66,
            marker=dict(color="rgba(198,40,40,0.06)" if f.urgence else "rgba(38,38,245,0.05)",
                        line=dict(color=ROUGE if f.urgence else couleur.get(f.chirurgien_id, "#888"), width=1.2)),
            hovertemplate=f"{lib}<br>{f.debut:%H:%M}–{f.fin:%H:%M}<extra></extra>", showlegend=False))
        fig.add_annotation(x=f.debut, y=nom, text=lib, showarrow=False, xanchor="left", yanchor="bottom",
                           yshift=bande * 0.33 + 4, font=dict(size=10, color="#4A5591"))

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
                y=[s.nom_affiche], x=[_ms(it.duree)], base=[it.debut], orientation="h", width=0.42,
                marker=dict(color=c, pattern=dict(shape="/" if p.ambulatoire else "", fgcolor="rgba(255,255,255,0.45)", fillmode="overlay"),
                            line=dict(color="#0E0E8C" if (moi and it.chirurgien_id == moi) else "white",
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
        # heure courante : temps écoulé grisé + trait plein bleu nuit (distinct du rouge des urgences) + étiquette
        fig.add_vrect(x0=datetime.combine(jour, time(7, 30)), x1=sim.maintenant, fillcolor="#0B0B45", opacity=0.06,
                      line_width=0, layer="below")
        fig.add_vline(x=sim.maintenant, line=dict(color=NUIT, width=3))
        fig.add_annotation(x=sim.maintenant, y=1, yref="paper", yanchor="bottom", text=f"<b>{sim.maintenant:%H:%M}</b>",
                           showarrow=False, bgcolor=NUIT, borderpad=4, font=dict(color="white", size=12))

    # légende sous l'axe, dans une marge réservée (elle ne recouvre plus le planning)
    rangs_legende = -(-len(vus) // 6) if vus else 0
    marge_bas = 30 + 26 * rangs_legende
    fig.update_layout(
        barmode="overlay", height=60 + marge_bas + hauteur_ligne * len(salles),
        margin=dict(l=10, r=10, t=34, b=marge_bas),
        xaxis=dict(type="date", range=[datetime.combine(jour, time(7, 30)), datetime.combine(jour, time(18, 0))],
                   tickformat="%Hh", dtick=3600 * 1000, gridcolor=GRILLE),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(ordre))),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)", font=POLICE,
        legend=dict(orientation="h", yref="container", y=0, yanchor="bottom", x=0, font=dict(size=11)),
        hoverlabel=dict(bgcolor="white", font_size=12))
    return fig


def occupation_hebergement(sim: S.Simulation) -> go.Figure:
    lits, places = sim.modele.hebergement.occupation()
    h = sim.modele.instance2.hebergement
    jours = sim.jours()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=jours, y=[lits.get(j, 0) for j in jours], name="Lits occupés", marker_color=BLEU))
    fig.add_trace(go.Bar(x=jours, y=[places.get(j, 0) for j in jours], name="Places ambulatoires", marker_color=MENTHE))
    fig.add_hline(y=h.cap_lits, line=dict(color=BLEU, dash="dash"),
                  annotation_text=f"capacité lits ({h.cap_lits} + {h.reserve_lits} de réserve)")
    fig.add_hline(y=h.cap_places, line=dict(color=MENTHE, dash="dot"),
                  annotation_text=f"capacité ambulatoire ({h.cap_places})", annotation_position="bottom right")
    if jours and jours[0] <= sim.maintenant.date() <= jours[-1]:
        fig.add_vline(x=datetime.combine(sim.maintenant.date(), time(0)), line=dict(color="#C62828", dash="dot"))
    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=20, b=10), plot_bgcolor="white",
                      paper_bgcolor="rgba(0,0,0,0)", font=POLICE,
                      legend=dict(orientation="h", y=-0.2), yaxis=dict(gridcolor=GRILLE, title="patients"),
                      xaxis=dict(tickvals=[j for j in jours if j.weekday() == 0],
                                 ticktext=[_jour_court(j) for j in jours if j.weekday() == 0]))
    return fig


def convergence(series: dict[str, list[tuple[float, float]]], titre: str = "") -> go.Figure:
    fig = go.Figure()
    for k, (nom, pts) in enumerate(series.items()):
        if pts:
            fig.add_trace(go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines", name=nom,
                                     line=dict(shape="hv", width=2, color=PALETTE[k % len(PALETTE)])))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30 if titre else 10, b=10), plot_bgcolor="white",
                      paper_bgcolor="rgba(0,0,0,0)", font=POLICE,
                      title=titre or None, xaxis=dict(title="temps de calcul (s)", gridcolor=GRILLE),
                      yaxis=dict(title="meilleur score (à minimiser)", gridcolor=GRILLE),
                      legend=dict(orientation="h", y=-0.25))
    return fig


def taux_bloc(taux: dict[date, float], aujourd_hui: date) -> go.Figure:
    """Taux d'occupation du bloc par jour ; la journée en cours est mise en évidence."""
    jours = list(taux)
    fig = go.Figure(go.Bar(
        x=[_jour_court(j) for j in jours], y=[taux[j] for j in jours],
        marker=dict(color=[BLEU if j == aujourd_hui else "#AEBDFC" for j in jours], cornerradius=4),
        hovertemplate="%{x} : %{y:.0f} %<extra></extra>", showlegend=False))
    if aujourd_hui in taux:
        fig.add_annotation(x=_jour_court(aujourd_hui), y=taux[aujourd_hui], text=f"aujourd'hui {taux[aujourd_hui]:.0f} %",
                           showarrow=False, yshift=12, font=dict(size=11, color="#17175E"))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10), plot_bgcolor="white", bargap=0.35,
                      paper_bgcolor="rgba(0,0,0,0)", font=POLICE,
                      yaxis=dict(range=[0, 110], ticksuffix=" %", gridcolor=GRILLE),
                      xaxis=dict(type="category", tickvals=[_jour_court(j) for j in jours if j.weekday() == 0]))
    return fig


def bloc_occupe(sim: S.Simulation, jour: date, hauteur_ligne: int = 54) -> go.Figure:
    """Occupation des salles sans aucune donnée patient ni chirurgien : cadres = plages ouvertes, gris = salle occupée."""
    salles = list(sim.modele.salles.values())
    ordre = [s.nom_affiche for s in salles]
    fig = go.Figure()
    for f in sim.fenetres_du_jour(jour):
        fig.add_trace(go.Bar(
            y=[sim.modele.salles[f.salle_id].nom_affiche], x=[_ms(f.fin - f.debut)], base=[f.debut], orientation="h",
            width=0.7, marker=dict(color="white", line=dict(color="#C9D3FB", width=1)),
            hovertemplate=f"Ouverte {f.debut:%H:%M}–{f.fin:%H:%M}<extra></extra>", showlegend=False))
    for s in salles:
        for it in s.du_jour(jour):
            fig.add_trace(go.Bar(
                y=[s.nom_affiche], x=[_ms(it.duree)], base=[it.debut], orientation="h", width=0.5,
                marker=dict(color="#8A93B8", line=dict(color="white", width=2), cornerradius=4),
                hovertemplate=f"Occupée {it.debut:%H:%M}–{it.fin:%H:%M}<extra></extra>", showlegend=False))
    if sim.maintenant.date() == jour:
        fig.add_vline(x=sim.maintenant, line=dict(color=NUIT, width=3))
        fig.add_annotation(x=sim.maintenant, y=1, yref="paper", yanchor="bottom", text=f"<b>{sim.maintenant:%H:%M}</b>",
                           showarrow=False, bgcolor=NUIT, borderpad=4, font=dict(color="white", size=12))
    fig.update_layout(
        barmode="overlay", height=90 + hauteur_ligne * len(salles), margin=dict(l=10, r=10, t=34, b=30),
        xaxis=dict(type="date", range=[datetime.combine(jour, time(7, 30)), datetime.combine(jour, time(18, 0))],
                   tickformat="%Hh", dtick=3600 * 1000, gridcolor=GRILLE),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(ordre))),
        plot_bgcolor="#F7F8FC", paper_bgcolor="rgba(0,0,0,0)", font=POLICE, hoverlabel=dict(bgcolor="white"))
    return fig
