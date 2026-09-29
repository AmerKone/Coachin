"""Plotly line charts ("courbes") for workout, nutrition, and body-metric progress.

Colors are the validated reference palette's categorical slots 1-4 (light and dark steps
checked for lightness, chroma, colorblind separation and contrast). In light mode slots 3-4
are below 3:1 contrast, so every multi-series chart direct-labels each line and pages offer a
table view. Text uses neutral ink, never a series color. One y-axis per chart.
"""

from datetime import date, timedelta
from typing import Any

import plotly.graph_objects as go
import streamlit as st

HEIGHT = 340
PLOT_HEIGHT = HEIGHT - 40 - 44  # minus top/bottom margins; used to space end labels

PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
              "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df"},
    "dark": {"series": ["#3987e5", "#d95926", "#199e70", "#c98500"],
             "text": "#ffffff", "muted": "#c3c2b7", "grid": "#3a3a37"},
}


def _theme() -> dict[str, Any]:
    try:
        mode = st.context.theme.type or "light"
    except AttributeError:
        mode = "light"
    return PALETTE.get(mode, PALETTE["light"])


def _layout(theme: dict[str, Any], y_title: str, show_legend: bool) -> dict[str, Any]:
    axis = {"showline": False, "zeroline": False, "tickfont": {"color": theme["muted"]}}
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": theme["text"]},
        "margin": {"l": 64, "r": 150, "t": 40 if show_legend else 16, "b": 44},
        "height": HEIGHT,
        "hovermode": "x unified",
        "showlegend": show_legend,
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "font": {"color": theme["text"]}},
        "xaxis": {**axis, "showgrid": False, "tickformat": "%d %b", "automargin": True, "showspikes": True,
                  "spikemode": "across", "spikethickness": 1, "spikecolor": theme["muted"], "spikedash": "dot"},
        "yaxis": {**axis, "gridcolor": theme["grid"], "gridwidth": 1, "automargin": True,
                  "title": {"text": y_title, "font": {"color": theme["muted"]}, "standoff": 12}},
    }


def _line(name: str, x: list, y: list, color: str, hover: str, width: int = 2, **extra) -> go.Scatter:
    return go.Scatter(
        x=x, y=y, name=name, mode="lines+markers", connectgaps=True,
        line={"color": color, "width": width},
        marker={"size": 8, "color": color, "line": {"width": 2, "color": "rgba(0,0,0,0)"}},
        hovertemplate=f"{name}: {hover}<extra></extra>", **extra,
    )


def _end_label(fig: go.Figure, theme: dict[str, Any], x, y: float, text: str) -> None:
    """Direct label at a line's last point, so identity never relies on color alone."""
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=10, align="left",
                       font={"color": theme["text"], "size": 12})


def _spread_labels(fig: go.Figure, theme: dict[str, Any], labels: list[tuple[Any, float, str]]) -> None:
    """Place end labels, nudging them apart (in pixels) when their y values are too close."""
    if not labels:
        return
    values = [y for trace in fig.data for y in (trace.y or []) if y is not None]
    span = (max(values) - min(values)) or 1.0
    min_gap = 34 / PLOT_HEIGHT * span  # ~two lines of 12px text
    placed: list[float] = []
    for x, y, text in sorted(labels, key=lambda label: label[1], reverse=True):
        target = y if not placed or placed[-1] - y >= min_gap else placed[-1] - min_gap
        placed.append(target)
        fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=10, align="left",
                           yshift=(target - y) / span * PLOT_HEIGHT, font={"color": theme["text"], "size": 12})


def rolling_average(points: list[tuple[date, float]], days: int = 7) -> list[float]:
    """Mean of the values within the trailing `days`-day window ending at each point."""
    averages = []
    for day, _ in points:
        window = [v for d, v in points if day - timedelta(days=days - 1) <= d <= day]
        averages.append(round(sum(window) / len(window), 2))
    return averages


def exercise_progress_chart(history: list[dict[str, Any]], exercise_name: str) -> go.Figure:
    """Estimated 1RM and top-set weight over time for one exercise (both in kg, one axis)."""
    theme = _theme()
    dates = [point["performed_at"] for point in history]
    reps = [p["top_set_reps"] for p in history]
    series = [("Estimated 1RM", [p["estimated_1rm_kg"] for p in history], theme["series"][0], "%{y:.1f} kg"),
              ("Top set", [p["top_set_weight_kg"] for p in history], theme["series"][1],
               "%{y:g} kg × %{customdata} reps")]
    fig = go.Figure()
    for name, values, color, hover in series:
        fig.add_trace(_line(name, dates, values, color, hover, customdata=reps))
        last = next(((d, v) for d, v in zip(reversed(dates), reversed(values)) if v is not None), None)
        if last:
            _end_label(fig, theme, last[0], last[1], f"{name}<br><b>{last[1]:g} kg</b>")
    fig.update_layout(**_layout(theme, "kg", show_legend=True))
    return fig


def strength_chart(exercises: list[dict[str, Any]]) -> go.Figure:
    """Estimated 1RM curves for up to four exercises (categorical slots in fixed order)."""
    theme = _theme()
    fig = go.Figure()
    labels = []
    for exercise, color in zip(exercises[:4], theme["series"]):
        days = [p["day"] for p in exercise["points"]]
        values = [p["estimated_1rm_kg"] for p in exercise["points"]]
        fig.add_trace(_line(exercise["name"], days, values, color, "%{y:.1f} kg"))
        labels.append((days[-1], values[-1],
                       f"{exercise['name']}<br><b>{values[-1]:g} kg</b> ({exercise['change_pct']:+g}%)"))
    _spread_labels(fig, theme, labels)
    fig.update_layout(**_layout(theme, "Estimated 1RM (kg)", show_legend=len(exercises) > 1))
    return fig


def body_weight_trend_chart(points: list[dict[str, Any]]) -> go.Figure:
    """Daily weigh-ins as faint dots with a 7-day rolling-average curve (same entity, one hue)."""
    theme = _theme()
    color = theme["series"][0]
    days = [date.fromisoformat(p["day"]) for p in points]
    weights = [p["weight_kg"] for p in points]
    average = rolling_average(list(zip(days, weights)))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days, y=weights, name="Weigh-ins", mode="markers",
                             marker={"size": 8, "color": color, "opacity": 0.45},
                             hovertemplate="Weigh-in: %{y:.1f} kg<extra></extra>"))
    fig.add_trace(_line("7-day average", days, average, color, "%{y:.1f} kg", width=3))
    _end_label(fig, theme, days[-1], average[-1], f"7-day average<br><b>{average[-1]:.1f} kg</b>")
    fig.update_layout(**_layout(theme, "kg", show_legend=True))
    return fig


def calories_chart(points: list[dict[str, Any]], target: float | None) -> go.Figure:
    """Calories per logged day, with the target as a dashed reference line (not a series)."""
    theme = _theme()
    days = [p["day"] for p in points]
    fig = go.Figure(_line("Calories", days, [p["calories"] for p in points], theme["series"][0], "%{y:,.0f} kcal"))
    if target:
        fig.add_hline(y=target, line={"color": theme["muted"], "width": 1, "dash": "dash"},
                      annotation_text=f"Target {target:,.0f}", annotation_position="right",
                      annotation_font_color=theme["muted"])
    fig.update_layout(**_layout(theme, "kcal", show_legend=False))
    return fig


def volume_chart(points: list[dict[str, Any]]) -> go.Figure:
    """Working sets per week (x = the Monday of each week)."""
    theme = _theme()
    weeks = [date.fromisoformat(p["week_start"]) for p in points]
    fig = go.Figure(_line("Sets", weeks, [p["sets"] for p in points], theme["series"][0], "%{y} sets"))
    fig.update_layout(**_layout(theme, "Sets per week", show_legend=False))
    fig.update_xaxes(tickvals=weeks, ticktext=[f"Wk of {w:%d %b}" for w in weeks])
    fig.update_yaxes(rangemode="tozero")
    return fig
