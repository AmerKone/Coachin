"""Plotly charts for workout, nutrition, and body-metric progress."""

from typing import Any

import plotly.graph_objects as go


def exercise_progress_chart(history: list[dict[str, Any]], exercise_name: str) -> go.Figure:
    """Estimated 1RM and top-set weight over time for one exercise."""
    raise NotImplementedError


def macro_vs_target_chart(summary: dict[str, Any]) -> go.Figure:
    """Bar chart of today's calories/macros against targets."""
    raise NotImplementedError


def body_weight_trend_chart(metrics: list[dict[str, Any]]) -> go.Figure:
    """Body weight with a 7-day rolling average."""
    raise NotImplementedError
