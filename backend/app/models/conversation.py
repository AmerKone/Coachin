"""Conversation history with the coaching agent."""

import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import MessageRole

if TYPE_CHECKING:
    from app.models.safety import SafetyEvent
    from app.models.user import User


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chat thread between a user and the coach."""

    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single turn in a conversation (text, optionally originating from/rendered to audio)."""

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(pg_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    is_voice: Mapped[bool] = mapped_column(default=False)
    """True when the user message was transcribed from audio."""
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    """Raw tool calls made by the agent for this turn, for auditing/debugging."""
    retrieved_sources: Mapped[list[str] | None] = mapped_column(JSON)
    """IDs of RAG chunks used to ground this response."""
    safety_flagged: Mapped[bool] = mapped_column(default=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    safety_events: Mapped[list["SafetyEvent"]] = relationship(back_populates="message")
