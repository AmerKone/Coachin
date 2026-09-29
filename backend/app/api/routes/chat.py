"""Text conversations with the coaching agent."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import Conversation
from app.schemas import ChatRequest, ChatResponse, ConversationRead, ConversationSummary
from app.services.chat_service import ChatService, CoachUnavailableError, ConversationNotFoundError

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_service(db: DbSession) -> ChatService:
    return ChatService(db)


Chat = Annotated[ChatService, Depends(get_chat_service)]


def run_turn(chat: ChatService, user, payload: ChatRequest, *, is_voice: bool = False) -> ChatResponse:
    try:
        return chat.handle_turn(user, payload, is_voice=is_voice)
    except ConversationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from None
    except CoachUnavailableError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="The coach is unavailable right now. Please try again.") from None


def _get_owned(chat: ChatService, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    conversation = chat.get_conversation(user_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.post("", response_model=ChatResponse)
def send_message(payload: ChatRequest, user: CurrentUser, chat: Chat) -> ChatResponse:
    """Send one user turn to the coach.

    Pipeline: safety screen -> agent (knowledge retrieval + tools) -> reply screen -> persist
    messages -> optional TTS.
    """
    return run_turn(chat, user, payload)


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user: CurrentUser, chat: Chat) -> list[Conversation]:
    """The user's conversations, most recently active first."""
    return chat.list_conversations(user.id)


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(conversation_id: uuid.UUID, user: CurrentUser, chat: Chat) -> Conversation:
    return _get_owned(chat, user.id, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, chat: Chat) -> None:
    chat.delete_conversation(_get_owned(chat, user.id, conversation_id))
