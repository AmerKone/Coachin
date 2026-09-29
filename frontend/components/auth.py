"""Login/registration UI and session-state helpers."""

import httpx
import streamlit as st

from client.api_client import ApiError, CoachinClient
from config import BACKEND_URL

_TOKEN_KEY = "access_token"
_USER_KEY = "user"


def get_client() -> CoachinClient | None:
    """Build an authenticated client from the token in `st.session_state`, or None if logged out.

    Only the token is kept in the session (not the client object), so a code change to
    `CoachinClient` takes effect immediately instead of leaving a stale instance around.
    """
    token = st.session_state.get(_TOKEN_KEY)
    return CoachinClient(token) if token else None


def current_user() -> dict | None:
    return st.session_state.get(_USER_KEY)


def logout() -> None:
    st.session_state.pop(_TOKEN_KEY, None)
    st.session_state.pop(_USER_KEY, None)


def require_login() -> CoachinClient:
    """Render the login form and `st.stop()` if not authenticated; otherwise return the client."""
    client = get_client()
    if client is None:
        render_login_form()
        st.stop()

    with st.sidebar:
        user = current_user() or {}
        st.caption(f"Signed in as **{user.get('full_name') or user.get('email', '')}**")
        if st.button("Log out", width="stretch"):
            logout()
            st.rerun()
    return client


def show_error(exc: Exception) -> None:
    """Display a failed API call's error message."""
    if isinstance(exc, ApiError):
        st.error(exc.detail)
    elif isinstance(exc, httpx.TransportError):
        st.error(f"Can't reach the Coachin backend at {BACKEND_URL}. Is it running?")
    else:
        raise exc


def handle_api_error(exc: Exception) -> None:
    """For signed-in pages: like `show_error`, but a 401 means the session expired, so log out."""
    if isinstance(exc, ApiError) and exc.status_code == 401:
        logout()
        st.rerun()
    show_error(exc)


def _sign_in(client: CoachinClient, email: str, password: str) -> None:
    token = client.login(email, password)
    st.session_state[_USER_KEY] = client.get_me()
    st.session_state[_TOKEN_KEY] = token
    st.rerun()


def render_login_form() -> None:
    """Tabs for sign-in and sign-up; stores the authenticated client in session state on success."""
    st.title("Coachin")
    st.write("Your AI fitness coach. Sign in or create an account to get started.")

    sign_in_tab, sign_up_tab = st.tabs(["Sign in", "Create account"])

    with sign_in_tab, st.form("sign_in"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            if not email or not password:
                st.error("Enter your email and password.")
            else:
                try:
                    _sign_in(CoachinClient(), email, password)
                except (ApiError, httpx.TransportError) as exc:
                    show_error(exc)

    with sign_up_tab, st.form("sign_up"):
        full_name = st.text_input("Name")
        new_email = st.text_input("Email", key="sign_up_email")
        new_password = st.text_input("Password", type="password", key="sign_up_password",
                                     help="At least 8 characters.")
        confirm = st.text_input("Confirm password", type="password")
        if st.form_submit_button("Create account", type="primary"):
            if new_password != confirm:
                st.error("Passwords don't match.")
            else:
                client = CoachinClient()
                try:
                    client.register(new_email, new_password, full_name or None)
                    _sign_in(client, new_email, new_password)
                except (ApiError, httpx.TransportError) as exc:
                    show_error(exc)
