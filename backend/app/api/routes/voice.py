"""Voice endpoints: transcription, speech synthesis, and full voice turns."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import ValidationError

from app.api.deps import CurrentUser
from app.api.routes.chat import Chat, run_turn
from app.schemas import ChatRequest, SpeechRequest, TranscriptionResponse, VoiceChatResponse
from app.services.voice_service import MAX_AUDIO_BYTES, VoiceError, VoiceService

router = APIRouter(prefix="/voice", tags=["voice"])


def get_voice_service() -> VoiceService:
    return VoiceService()


Voice = Annotated[VoiceService, Depends(get_voice_service)]


def _voice_error(exc: VoiceError) -> HTTPException:
    code = status.HTTP_502_BAD_GATEWAY if exc.upstream else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(exc))


async def _read_audio(audio: UploadFile) -> bytes:
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Recording is too large (max 25 MB).")
    return data


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(user: CurrentUser, voice: Voice, audio: UploadFile = File(...)) -> TranscriptionResponse:
    """Speech-to-text only. Accepts webm/wav/mp3/m4a up to 25 MB."""
    try:
        return voice.transcribe(await _read_audio(audio), audio.filename or "audio.wav")
    except VoiceError as exc:
        raise _voice_error(exc) from None


@router.post("/speak", response_class=Response)
def speak(payload: SpeechRequest, user: CurrentUser, voice: Voice) -> Response:
    """Text-to-speech only. Returns `audio/mpeg` bytes."""
    preferred = payload.voice or (user.profile.preferred_tts_voice if user.profile else None)
    try:
        return Response(content=voice.synthesize(payload.text, preferred), media_type="audio/mpeg")
    except VoiceError as exc:
        raise _voice_error(exc) from None


@router.post("/chat", response_model=VoiceChatResponse)
async def voice_chat(
    user: CurrentUser,
    chat: Chat,
    voice: Voice,
    audio: UploadFile = File(...),
    conversation_id: uuid.UUID | None = Form(None),
    timezone: str = Form("UTC"),
    speak_response: bool = Form(True),
) -> VoiceChatResponse:
    """Full voice turn: transcribe -> chat pipeline (safety, agent, tools) -> spoken reply."""
    try:
        transcript = voice.transcribe(await _read_audio(audio), audio.filename or "audio.wav").text
    except VoiceError as exc:
        raise _voice_error(exc) from None
    if not transcript:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="I didn't catch that. Please try again a little closer to the microphone.")
    try:
        request = ChatRequest(message=transcript[:4000], conversation_id=conversation_id,
                              speak_response=speak_response, timezone=timezone)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    response = run_turn(chat, user, request, is_voice=True)
    return VoiceChatResponse(**response.model_dump(), transcript=transcript)
