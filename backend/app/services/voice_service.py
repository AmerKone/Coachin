"""Speech-to-text (Whisper) and text-to-speech (OpenAI TTS)."""

from typing import BinaryIO

from app.schemas import TranscriptionResponse

MAX_AUDIO_BYTES = 25 * 1024 * 1024
"""Whisper's upload limit."""

SUPPORTED_AUDIO_TYPES = {"audio/webm", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/m4a"}


class VoiceService:
    """Converts between user audio and text."""

    def transcribe(self, audio: BinaryIO, filename: str) -> TranscriptionResponse:
        """Transcribe an audio file with Whisper.

        Raises:
            ValueError: unsupported format or file exceeds `MAX_AUDIO_BYTES`.
        """
        raise NotImplementedError

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Render `text` to MP3 bytes. Long text is chunked to respect the TTS input limit."""
        raise NotImplementedError
