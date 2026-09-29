"""Coachin Streamlit entrypoint (home / dashboard).

Run with: `streamlit run frontend/app.py`
Additional pages live in `pages/` and appear in the sidebar automatically.
"""

import streamlit as st

from components.auth import require_login  # noqa: F401

st.set_page_config(page_title="Coachin", page_icon="🏋️", layout="wide")


def main() -> None:
    """Dashboard: greeting, today's workout, nutrition snapshot, and quick links.

    Redirects new users without a profile to the Profile page for onboarding.
    """
    raise NotImplementedError


if __name__ == "__main__":
    main()
