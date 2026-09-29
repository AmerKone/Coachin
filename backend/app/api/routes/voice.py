"""Voice endpoints: Whisper transcription, TTS synthesis, and full voice turns."""

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from app.api.deps import CurrentUser, DbSession
from app.schemas import SpeechRequest, TranscriptionResponse, VoiceChatResponse

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(user: CurrentUser, audio: UploadFile = File(...)) -> TranscriptionResponse:
    """Speech-to-text only. Accepts webm/wav/mp3/m4a up to 25 MB (Whisper limit)."""
    raise NotImplementedError


@router.post("/speak", response_class=Response)
async def speak(payload: SpeechRequest, user: CurrentUser) -> Response:
    """Text-to-speech only. Returns `audio/mpeg` bytes."""
    raise NotImplementedError


@router.post("/chat", response_model=VoiceChatResponse)
async def voice_chat(
    user: CurrentUser,
    db: DbSession,
    audio: UploadFile = File(...),
    conversation_id: uuid.UUID | None = Form(None),
) -> VoiceChatResponse:
    """Full voice turn: transcribe -> chat pipeline -> synthesize reply audio."""
    raise NotImplementedError
