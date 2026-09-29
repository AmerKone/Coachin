"""Orchestrates one conversational turn (text or voice)."""

import base64
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.coach import CoachAgent
from app.models import Conversation, Message, User
from app.models.enums import MessageRole, SafetyAction
from app.schemas import ChatRequest, ChatResponse, MessageRead, SafetyAssessment, SafetyNotice
from app.services.llm_client import LLMError
from app.services.safety_service import SHORT_CIRCUIT_ACTIONS, SafetyService
from app.services.voice_service import VoiceError, VoiceService

logger = logging.getLogger(__name__)


class ConversationNotFoundError(Exception):
    pass


class CoachUnavailableError(Exception):
    """The LLM couldn't be reached; the user message is kept, no reply was produced."""


def _notice(assessment: SafetyAssessment, message: str | None = None) -> SafetyNotice:
    return SafetyNotice(
        category=assessment.category, severity=assessment.severity,
        action_taken=assessment.recommended_action,
        message=message or assessment.user_facing_message or "",
    )


class ChatService:
    def __init__(
        self,
        db: Session,
        agent: CoachAgent | None = None,
        safety: SafetyService | None = None,
        voice: VoiceService | None = None,
    ) -> None:
        self.db = db
        self.agent = agent or CoachAgent(db)
        self.safety = safety or SafetyService(db)
        self.voice = voice or VoiceService()

    # Conversations

    def list_conversations(self, user_id: uuid.UUID) -> list[Conversation]:
        return list(self.db.scalars(
            select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
        ))

    def get_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        return self.db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id))

    def delete_conversation(self, conversation: Conversation) -> None:
        self.db.delete(conversation)
        self.db.commit()

    # Turns

    def handle_turn(self, user: User, request: ChatRequest, *, is_voice: bool = False) -> ChatResponse:
        """Process a user message end-to-end.

        1. Load or create the conversation; persist the user message.
        2. Screen the input. Red-flag matches (emergency, referral, blocked) return the fixed
           safety message without invoking the agent; softer flags become an agent instruction.
        3. Run the coach agent (knowledge retrieval + tools).
        4. Screen the reply; unsafe advice is replaced by a safe message.
        5. Persist the reply and any safety events; synthesize audio if requested.

        Raises:
            ConversationNotFoundError: `conversation_id` isn't one of the user's conversations.
            CoachUnavailableError: the LLM couldn't be reached.
        """
        if request.conversation_id is not None:
            conversation = self.get_conversation(user.id, request.conversation_id)
            if conversation is None:
                raise ConversationNotFoundError
        else:
            conversation = Conversation(user_id=user.id, title=request.message[:60])
            self.db.add(conversation)
            self.db.flush()
        history = list(self.db.scalars(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))

        user_message = Message(conversation_id=conversation.id, role=MessageRole.USER,
                               content=request.message, is_voice=is_voice)
        self.db.add(user_message)
        self.db.flush()

        assessment = self.safety.screen_input(request.message, user.profile)
        notice = None
        actions: list[str] = []
        tool_calls, sources = None, None

        if assessment.is_flagged:
            user_message.safety_flagged = True
            self.safety.record_event(user.id, assessment, request.message, user_message.id)

        if assessment.is_flagged and assessment.recommended_action in SHORT_CIRCUIT_ACTIONS:
            reply_text = assessment.user_facing_message or ""
            notice = _notice(assessment)
        else:
            instruction = None
            if assessment.is_flagged and assessment.recommended_action == SafetyAction.CAUTIONED:
                instruction = (f"possible {assessment.category} concern ({assessment.rationale}). Answer carefully, "
                               "avoid advice that could worsen it, and suggest seeing a professional if relevant.")
            self.db.commit()  # keep the user message even if the agent fails
            try:
                result = self.agent.run(user, request.message, history, request.timezone, instruction)
            except LLMError as exc:
                raise CoachUnavailableError(str(exc)) from exc
            reply_text, actions = result.reply, result.actions
            tool_calls, sources = result.tool_calls or None, result.retrieved_sources or None

            output_check = self.safety.screen_output(reply_text)
            if output_check.is_flagged:
                self.safety.record_event(user.id, output_check, reply_text)
                reply_text = output_check.user_facing_message or ""
                notice = _notice(output_check)
            elif assessment.is_flagged and assessment.recommended_action == SafetyAction.CAUTIONED:
                notice = _notice(assessment, "Your coach answered with extra care because of a possible health "
                                             "concern. If symptoms are severe or getting worse, see a professional.")

        assistant_message = Message(
            conversation_id=conversation.id, role=MessageRole.ASSISTANT, content=reply_text,
            tool_calls=tool_calls, retrieved_sources=sources, safety_flagged=notice is not None,
        )
        self.db.add(assistant_message)
        conversation.updated_at = func.now()  # most recently active conversations first
        self.db.commit()
        self.db.refresh(user_message)
        self.db.refresh(assistant_message)
        self.db.refresh(conversation)

        audio = None
        if request.speak_response:
            try:
                audio = base64.b64encode(self.voice.synthesize(reply_text, self._voice_for(user))).decode()
            except VoiceError as exc:  # the text reply is still useful without audio
                logger.warning("TTS failed: %s", exc)

        return ChatResponse(
            conversation_id=conversation.id,
            user_message=MessageRead.model_validate(user_message),
            assistant_message=MessageRead.model_validate(assistant_message),
            safety_notice=notice,
            audio_base64=audio,
            actions=actions,
        )

    @staticmethod
    def _voice_for(user: User) -> str | None:
        return user.profile.preferred_tts_voice if user.profile else None
