"""Medical/wellbeing safety guardrails.

Two layers run on every user input before the agent sees it:

1. A fast keyword/regex screen for red-flag phrases (e.g. chest pain, fainting,
   "stop eating") that can short-circuit to an emergency or referral response.
2. An LLM classifier returning a `SafetyAssessment` for subtler cases.

The agent's output is also checked (e.g. no calorie targets below safe minimums, no
diagnosing or medication advice). Every flagged turn is persisted as a `SafetyEvent`.
"""

import uuid

from sqlalchemy.orm import Session

from app.models import SafetyEvent, UserProfile
from app.schemas import SafetyAssessment

MIN_SAFE_DAILY_CALORIES = 1200
"""Floor below which the coach will never recommend an intake target."""


class SafetyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def screen_input(self, text: str, profile: UserProfile | None) -> SafetyAssessment:
        """Classify a user message for medical/wellbeing risk (keyword pass, then LLM)."""
        raise NotImplementedError

    def screen_output(self, text: str, profile: UserProfile | None) -> SafetyAssessment:
        """Check an agent response for unsafe advice before it is returned to the user."""
        raise NotImplementedError

    def screen_profile(self, profile: UserProfile) -> SafetyAssessment:
        """Evaluate injuries/medical conditions at onboarding to decide if clearance is needed."""
        raise NotImplementedError

    def record_event(
        self,
        user_id: uuid.UUID,
        assessment: SafetyAssessment,
        trigger_text: str,
        message_id: uuid.UUID | None = None,
    ) -> SafetyEvent:
        """Persist a flagged assessment as a `SafetyEvent`."""
        raise NotImplementedError
