"""Voice interaction widgets: microphone capture and reply playback."""

import streamlit as st  # noqa: F401


def record_audio(key: str = "voice_input") -> bytes | None:
    """Show a microphone recorder (`st.audio_input`) and return the WAV bytes once recorded."""
    raise NotImplementedError


def play_audio(audio_base64: str, autoplay: bool = True) -> None:
    """Decode and play an MP3 reply from the backend."""
    raise NotImplementedError
