"""Plotly charts for workout, nutrition, and body-metric progress.

Colors come from the validated reference palette (categorical slots 1-2, light and dark
steps checked for contrast and colorblind separation); text uses neutral ink, never the
series color.
"""

from typing import Any

import plotly.graph_objects as go
import streamlit as st

PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834"], "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df"},
    "dark": {"series": ["#3987e5", "#d95926"], "text": "#ffffff", "muted": "#c3c2b7", "grid": "#3a3a37"},
}


def _theme() -> dict[str, Any]:
    try:
        mode = st.context.theme.type or "light"
    except AttributeError:
        mode = "light"
    return PALETTE.get(mode, PALETTE["light"])


def _base_layout(theme: dict[str, Any], y_title: str) -> dict[str, Any]:
    axis = {"showline": False, "zeroline": False, "tickfont": {"color": theme["muted"]}}
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": theme["text"]},
        "margin": {"l": 8, "r": 72, "t": 32, "b": 8},
        "hovermode": "x unified",
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "font": {"color": theme["text"]}},
        "xaxis": {**axis, "showgrid": False, "showspikes": True, "spikemode": "across",
                  "spikethickness": 1, "spikecolor": theme["muted"], "spikedash": "dot"},
        "yaxis": {**axis, "gridcolor": theme["grid"], "gridwidth": 1,
                  "title": {"text": y_title, "font": {"color": theme["muted"]}}},
    }


def exercise_progress_chart(history: list[dict[str, Any]], exercise_name: str) -> go.Figure:
    """Estimated 1RM and top-set weight over time for one exercise (both in kg, one axis)."""
    theme = _theme()
    dates = [point["performed_at"] for point in history]
    series = [
        ("Estimated 1RM", [p["estimated_1rm_kg"] for p in history], theme["series"][0],
         "%{y:.1f} kg"),
        ("Top set", [p["top_set_weight_kg"] for p in history], theme["series"][1],
         "%{y:g} kg × %{customdata} reps"),
    ]
    fig = go.Figure()
    for name, values, color, value_format in series:
        fig.add_trace(go.Scatter(
            x=dates, y=values, name=name, mode="lines+markers",
            line={"color": color, "width": 2},
            marker={"size": 8, "color": color, "line": {"width": 2, "color": "rgba(0,0,0,0)"}},
            customdata=[p["top_set_reps"] for p in history],
            hovertemplate=f"{name}: {value_format}<extra></extra>",
            connectgaps=True,
        ))
        last = next(((d, v) for d, v in zip(reversed(dates), reversed(values)) if v is not None), None)
        if last:  # direct label at the line end so identity never relies on color alone
            fig.add_annotation(x=last[0], y=last[1], text=f"{name}<br><b>{last[1]:g} kg</b>",
                               showarrow=False, xanchor="left", xshift=10, align="left",
                               font={"color": theme["text"], "size": 12})
    fig.update_layout(**_base_layout(theme, "kg"), height=340)
    fig.update_xaxes(tickformat="%b %d")
    return fig


def body_weight_trend_chart(metrics: list[dict[str, Any]]) -> go.Figure:
    """Body weight with a 7-day rolling average."""
    raise NotImplementedError
