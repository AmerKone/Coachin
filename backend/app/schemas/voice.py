"""Schemas for speech-to-text and text-to-speech endpoints.

Audio *uploads* arrive as multipart `UploadFile`s, so only JSON bodies/responses are here.
"""

from pydantic import Field

from app.schemas.chat import ChatResponse
from app.schemas.common import CoachinSchema


class TranscriptionResponse(CoachinSchema):
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class SpeechRequest(CoachinSchema):
    text: str = Field(min_length=1, max_length=4096)
    voice: str | None = None
    """Overrides the user's preferred / default TTS voice."""


class VoiceChatResponse(ChatResponse):
    """Result of a full voice turn: transcribe -> agent -> synthesize."""

    transcript: str
