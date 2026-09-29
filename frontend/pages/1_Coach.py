"""Voice + text chat with the coach.

Conversation history as chat bubbles; a microphone recorder for voice turns and a chat
input for text turns. Replies can be read aloud; safety notices and actions the coach took
(logged a set, a meal...) are shown with the reply.
"""

from typing import Any

import httpx
import streamlit as st

from client.api_client import ApiError, CoachinClient
from components.auth import handle_api_error, require_login
from components.local_time import local_tz_name
from components.safety import render_disclaimer, render_safety_notice
from components.voice import play_audio, record_audio

API_ERRORS = (ApiError, httpx.TransportError)
ACTION_TEXT = {
    "logged_set": "✅ Set logged",
    "logged_meal": "🍽️ Meal logged",
    "logged_weight": "⚖️ Weight recorded",
    "updated_program": "🗓️ Program updated",
}
SUGGESTIONS = ["What's my workout today?", "I just had two eggs and toast", "How much protein should I eat?"]


def render_sidebar(client: CoachinClient) -> None:
    with st.sidebar:
        st.subheader("Conversations")
        if st.button("➕ New conversation", width="stretch"):
            st.session_state.pop("conversation_id", None)
            st.session_state.pop("last_turn", None)
            st.rerun()
        try:
            conversations = client.list_conversations()
        except API_ERRORS as exc:
            handle_api_error(exc)
            return
        for conversation in conversations[:15]:
            current = conversation["id"] == st.session_state.get("conversation_id")
            label = ("▶ " if current else "") + (conversation["title"] or "Conversation")[:40]
            if st.button(label, key=f"conv_{conversation['id']}", width="stretch"):
                st.session_state["conversation_id"] = conversation["id"]
                st.session_state.pop("last_turn", None)
                st.rerun()
        st.toggle("🔊 Speak replies", value=True, key="speak_replies")


def send(client: CoachinClient, *, text: str | None = None, audio: bytes | None = None) -> None:
    """Send one turn (text or voice) and remember the result for display after rerun."""
    conversation_id = st.session_state.get("conversation_id")
    speak = st.session_state.get("speak_replies", True)
    with st.spinner("Your coach is thinking…"):
        try:
            if audio is not None:
                result = client.voice_chat(audio, "recording.wav", conversation_id, speak, local_tz_name())
            else:
                result = client.chat(text or "", conversation_id, speak, local_tz_name())
        except API_ERRORS as exc:
            handle_api_error(exc)
            return
    st.session_state["conversation_id"] = result["conversation_id"]
    st.session_state["last_turn"] = result
    st.rerun()


def render_messages(client: CoachinClient) -> None:
    conversation_id = st.session_state.get("conversation_id")
    last_turn: dict[str, Any] | None = st.session_state.get("last_turn")
    if conversation_id is None:
        with st.chat_message("assistant", avatar="🏋️"):
            st.write("Hi! I'm your Coachin coach. Ask me about today's workout, tell me what you ate, "
                     "or log your sets as you go. Use the microphone or type below.")
            cols = st.columns(len(SUGGESTIONS))
            for column, suggestion in zip(cols, SUGGESTIONS):
                if column.button(suggestion, key=f"suggest_{suggestion}"):
                    send(client, text=suggestion)
        return

    try:
        conversation = client.get_conversation(conversation_id)
    except API_ERRORS as exc:
        handle_api_error(exc)
        return
    messages = conversation["messages"]
    for index, message in enumerate(messages):
        is_user = message["role"] == "user"
        with st.chat_message(message["role"], avatar="🙂" if is_user else "🏋️"):
            st.write(("🎙️ " if message["is_voice"] else "") + message["content"])
            is_latest_reply = (last_turn and not is_user and index == len(messages) - 1
                               and message["id"] == last_turn["assistant_message"]["id"])
            if is_latest_reply:
                render_safety_notice(last_turn["safety_notice"])
                if last_turn["actions"]:
                    st.caption("  ·  ".join(ACTION_TEXT.get(a, a) for a in last_turn["actions"]))
                if last_turn.get("audio_base64"):
                    play_audio(last_turn["audio_base64"], autoplay=not last_turn.get("played"))
                    last_turn["played"] = True


def main() -> None:
    client = require_login()
    st.title("Coach")
    render_sidebar(client)
    render_messages(client)

    # A fresh key per recording clears the widget after each voice turn.
    st.session_state.setdefault("recorder_key", 0)
    audio = record_audio(key=f"recorder_{st.session_state['recorder_key']}")
    if audio:
        st.session_state["recorder_key"] += 1
        send(client, audio=audio)
    if text := st.chat_input("Type a message"):
        send(client, text=text)
    render_disclaimer()


main()
