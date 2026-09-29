"""Schemas for text/voice conversations with the coach and safety events."""

import uuid
from datetime import datetime

from pydantic import Field

from app.models.enums import MessageRole, SafetyAction, SafetyCategory, SafetySeverity
from app.schemas.common import CoachinSchema, TimestampedReadSchema

# --- Messages -------------------------------------------------------------


class ChatRequest(CoachinSchema):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    """Omit to start a new conversation."""
    speak_response: bool = False
    """If true, the response also includes synthesized audio."""


class MessageRead(TimestampedReadSchema):
    role: MessageRole
    content: str
    is_voice: bool
    safety_flagged: bool


class SafetyNotice(CoachinSchema):
    """Surfaced to the UI when a guardrail fired on this turn."""

    category: SafetyCategory
    severity: SafetySeverity
    action_taken: SafetyAction
    message: str


class ChatResponse(CoachinSchema):
    conversation_id: uuid.UUID
    user_message: MessageRead
    assistant_message: MessageRead
    safety_notice: SafetyNotice | None = None
    audio_base64: str | None = None
    """MP3 audio of the assistant reply when `speak_response` was requested."""
    actions: list[str] = Field(default_factory=list)
    """Side effects performed by the agent, e.g. ["logged_meal", "updated_program"]."""


class ConversationSummary(TimestampedReadSchema):
    title: str | None


class ConversationRead(ConversationSummary):
    messages: list[MessageRead]


# --- Safety ---------------------------------------------------------------


class SafetyAssessment(CoachinSchema):
    """Output of the safety classifier for a single user input."""

    is_flagged: bool
    category: SafetyCategory | None = None
    severity: SafetySeverity | None = None
    recommended_action: SafetyAction = SafetyAction.LOGGED
    rationale: str | None = None
    user_facing_message: str | None = None


class SafetyEventRead(TimestampedReadSchema):
    message_id: uuid.UUID | None
    category: SafetyCategory
    severity: SafetySeverity
    action_taken: SafetyAction
    trigger_text: str
    rationale: str | None
