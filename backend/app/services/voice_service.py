"""Speech-to-text and text-to-speech via the OpenAI audio API.

Models come from settings (`OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL`): `whisper-1` / `tts-1` by
default; `gpt-4o-mini-transcribe` / `gpt-4o-mini-tts` also work, and the latter accepts a
speaking-style instruction.
"""

import openai

from app.config import get_settings
from app.schemas import TranscriptionResponse
from app.services.llm_client import get_openai_client

MAX_AUDIO_BYTES = 25 * 1024 * 1024
"""OpenAI's upload limit for transcription."""

SUPPORTED_AUDIO_SUFFIXES = {".webm", ".wav", ".mp3", ".mp4", ".m4a", ".mpeg", ".mpga", ".ogg", ".flac"}
MAX_TTS_CHARS = 4096
VOICES = {"alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}
TTS_STYLE = "Speak like a warm, upbeat personal trainer: clear, encouraging and not too fast."


class VoiceError(Exception):
    """Audio couldn't be processed. `upstream` is True when the OpenAI API failed."""

    def __init__(self, message: str, upstream: bool = False) -> None:
        super().__init__(message)
        self.upstream = upstream


def _chunks(text: str, limit: int = MAX_TTS_CHARS) -> list[str]:
    """Split text into <= `limit`-character pieces at sentence (or word) boundaries."""
    text = " ".join(text.split())
    pieces: list[str] = []
    while len(text) > limit:
        cut = max(text.rfind(". ", 0, limit), text.rfind("? ", 0, limit), text.rfind("! ", 0, limit))
        cut = cut + 1 if cut > 0 else (text.rfind(" ", 0, limit) if text.rfind(" ", 0, limit) > 0 else limit)
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        pieces.append(text)
    return pieces


class VoiceService:
    """Converts between user audio and text."""

    def transcribe(self, audio: bytes, filename: str) -> TranscriptionResponse:
        """Transcribe an audio file.

        Raises:
            VoiceError: empty, too large or unsupported audio, or the API failed.
        """
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in SUPPORTED_AUDIO_SUFFIXES:
            raise VoiceError(f"Unsupported audio format {suffix or '(none)'}; use webm, wav, mp3 or m4a.")
        if not audio:
            raise VoiceError("The audio file is empty.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("The recording is too long (max 25 MB).")
        try:
            result = get_openai_client().audio.transcriptions.create(
                model=get_settings().openai_stt_model, file=(filename, audio))
        except openai.BadRequestError as exc:
            raise VoiceError(f"Couldn't transcribe that audio: {exc.message}") from exc
        except openai.OpenAIError as exc:
            raise VoiceError(f"Transcription service failed: {exc}", upstream=True) from exc
        return TranscriptionResponse(text=result.text.strip())

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """Render `text` to MP3 bytes. Long text is split at sentence boundaries and joined
        (MP3 frames concatenate cleanly).

        Raises:
            VoiceError: empty text or the API failed.
        """
        if not text.strip():
            raise VoiceError("Nothing to say.")
        settings = get_settings()
        voice = voice if voice in VOICES else settings.openai_tts_voice
        extra = {"instructions": TTS_STYLE} if settings.openai_tts_model.startswith("gpt-") else {}
        audio = b""
        try:
            for piece in _chunks(text):
                response = get_openai_client().audio.speech.create(
                    model=settings.openai_tts_model, voice=voice, input=piece, response_format="mp3", **extra)
                audio += response.content
        except openai.OpenAIError as exc:
            raise VoiceError(f"Speech service failed: {exc}", upstream=True) from exc
        return audio
