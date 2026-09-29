"""Onboarding / profile settings.

Goal, level, schedule, equipment, injuries & medical conditions (with a clearance
checkbox), dietary preferences, macro targets, and preferred coach voice.
"""

import streamlit as st  # noqa: F401

from components.auth import require_login  # noqa: F401
from components.safety import render_disclaimer  # noqa: F401


def main() -> None:
    raise NotImplementedError


main()
