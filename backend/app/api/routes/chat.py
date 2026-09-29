"""Text conversations with the coaching agent."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import ChatRequest, ChatResponse, ConversationRead, ConversationSummary

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def send_message(payload: ChatRequest, user: CurrentUser, db: DbSession) -> ChatResponse:
    """Send one user turn to the coach.

    Pipeline: safety screen -> agent (RAG + tools) -> persist messages -> optional TTS.
    """
    raise NotImplementedError


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user: CurrentUser, db: DbSession) -> list[ConversationSummary]:
    raise NotImplementedError


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ConversationRead:
    raise NotImplementedError


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    raise NotImplementedError
