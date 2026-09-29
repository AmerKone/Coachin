"""Rendering of safety notices returned by the backend."""

from typing import Any

import streamlit as st


def render_safety_notice(notice: dict[str, Any] | None) -> None:
    """Show a prominent banner (error style for emergency/blocked, warning otherwise)."""
    if not notice:
        return
    action = notice["action_taken"]
    if action == "emergency":
        st.error("**This may be an emergency.** Stop exercising and get help now.", icon="🚨")
    elif action in ("blocked", "referred"):
        st.warning("**Please check with a professional.** Your coach can't safely advise on this.", icon="⚠️")
    else:
        st.info(notice["message"], icon="🩺")


def render_disclaimer() -> None:
    """Persistent footer: Coachin is not a substitute for professional medical advice."""
    st.caption(
        "Coachin provides general fitness guidance and is not a substitute for professional "
        "medical advice. Consult a doctor before starting a new exercise or nutrition program, "
        "especially if you have a medical condition, injury, or are pregnant."
    )
