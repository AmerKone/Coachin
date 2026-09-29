"""Weekly training program view and generation.

Shows the active program by week (tabs) with each day's exercises and targets; offers a
form to generate a new program and to activate/archive programs.
"""

import streamlit as st  # noqa: F401

from components.auth import require_login  # noqa: F401


def main() -> None:
    require_login()
    st.title("Program")
    st.info("Personalized weekly programs are coming soon.")


main()
