"""Voice interaction widgets: microphone capture and reply playback."""

import base64

import streamlit as st


def record_audio(key: str, label: str = "Talk to your coach") -> bytes | None:
    """Show a microphone recorder (`st.audio_input`) and return the WAV bytes once recorded."""
    recording = st.audio_input(label, key=key)
    return recording.getvalue() if recording is not None else None


def play_audio(audio_base64: str, autoplay: bool = True) -> None:
    """Decode and play an MP3 reply from the backend."""
    st.audio(base64.b64decode(audio_base64), format="audio/mpeg", autoplay=autoplay)
