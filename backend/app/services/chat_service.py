"""Orchestrates one conversational turn (text or voice)."""

from sqlalchemy.orm import Session

from app.agent.coach import CoachAgent
from app.models import User
from app.schemas import ChatRequest, ChatResponse
from app.services.safety_service import SafetyService
from app.services.voice_service import VoiceService


class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.safety = SafetyService(db)
        self.voice = VoiceService()

    def handle_turn(self, user: User, request: ChatRequest, *, is_voice: bool = False) -> ChatResponse:
        """Process a user message end-to-end.

        1. Load or create the conversation; persist the user message.
        2. `SafetyService.screen_input` — on BLOCKED/EMERGENCY return the safety response
           without invoking the agent.
        3. Run `CoachAgent` with conversation history, profile context, and RAG.
        4. `SafetyService.screen_output` on the draft reply.
        5. Persist the assistant message (+ any `SafetyEvent`s).
        6. Synthesize audio if `request.speak_response`.
        """
        raise NotImplementedError
