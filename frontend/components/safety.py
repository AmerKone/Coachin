"""Rendering of safety notices returned by the backend."""

from typing import Any

import streamlit as st


def render_safety_notice(notice: dict[str, Any] | None) -> None:
    """Show a prominent banner (error style for emergency/blocked, warning otherwise)."""
    raise NotImplementedError


def render_disclaimer() -> None:
    """Persistent footer: Coachin is not a substitute for professional medical advice."""
    st.caption(
        "Coachin provides general fitness guidance and is not a substitute for professional "
        "medical advice. Consult a doctor before starting a new exercise or nutrition program, "
        "especially if you have a medical condition, injury, or are pregnant."
    )
