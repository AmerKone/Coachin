"""Login/registration UI and session-state helpers."""

import streamlit as st  # noqa: F401

from client.api_client import CoachinClient


def get_client() -> CoachinClient | None:
    """Return the authenticated client from `st.session_state`, or None if logged out."""
    raise NotImplementedError


def require_login() -> CoachinClient:
    """Render the login form and `st.stop()` if not authenticated; otherwise return the client."""
    raise NotImplementedError


def render_login_form() -> None:
    """Tabs for sign-in and sign-up; stores the token in session state on success."""
    raise NotImplementedError
