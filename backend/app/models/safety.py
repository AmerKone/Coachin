"""Audit log of safety-guardrail triggers."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import SafetyAction, SafetyCategory, SafetySeverity

if TYPE_CHECKING:
    from app.models.conversation import Message
    from app.models.user import User


class SafetyEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Recorded whenever the safety layer detects a medical or wellbeing concern."""

    __tablename__ = "safety_events"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    category: Mapped[SafetyCategory] = mapped_column(pg_enum(SafetyCategory, "safety_category"))
    severity: Mapped[SafetySeverity] = mapped_column(pg_enum(SafetySeverity, "safety_severity"))
    action_taken: Mapped[SafetyAction] = mapped_column(pg_enum(SafetyAction, "safety_action"))
    trigger_text: Mapped[str] = mapped_column(Text)
    """The user text that triggered the guardrail."""
    rationale: Mapped[str | None] = mapped_column(Text)
    """Classifier explanation for why this was flagged."""

    user: Mapped["User"] = relationship(back_populates="safety_events")
    message: Mapped["Message | None"] = relationship(back_populates="safety_events")
