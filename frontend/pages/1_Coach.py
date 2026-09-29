"""Voice + text chat with the coach.

Layout: conversation history (st.chat_message), a microphone recorder for voice turns, a
chat input for text turns, auto-played TTS replies, and safety notices inline.
"""

import streamlit as st  # noqa: F401

from components.auth import require_login  # noqa: F401
from components.safety import render_safety_notice  # noqa: F401
from components.voice import play_audio, record_audio  # noqa: F401


def main() -> None:
    require_login()
    st.title("Coach")
    st.info("Voice and text chat with your coach is coming soon.")


main()
