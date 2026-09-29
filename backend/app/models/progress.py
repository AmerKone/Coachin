"""Body metrics and monthly progress report models."""

import uuid
from datetime import date, datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class BodyMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A point-in-time body measurement (weight, body fat, circumferences)."""

    __tablename__ = "body_metrics"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    weight_kg: Mapped[float | None]
    body_fat_pct: Mapped[float | None]
    waist_cm: Mapped[float | None]
    resting_heart_rate: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="body_metrics")


class ProgressReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A generated monthly progress report.

    `metrics` holds the computed numbers (volume, PRs, adherence, macro averages, weight
    trend); `summary` and `recommendations` are the LLM-written narrative.
    """

    __tablename__ = "progress_reports"
    __table_args__ = (UniqueConstraint("user_id", "period_start", name="uq_report_user_period"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text)
    recommendations: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="progress_reports")
