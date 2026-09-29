"""Nutrition logging model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import EntrySource, MealType

if TYPE_CHECKING:
    from app.models.user import User


class NutritionLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A meal or snack the user logged, with estimated macros."""

    __tablename__ = "nutrition_logs"
    __table_args__ = (
        CheckConstraint(
            "calories >= 0 AND protein_g >= 0 AND carbs_g >= 0 AND fat_g >= 0",
            name="ck_nutrition_non_negative",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    meal_type: Mapped[MealType] = mapped_column(pg_enum(MealType, "meal_type"))
    description: Mapped[str] = mapped_column(Text)
    """What was eaten, as described by the user (e.g. transcribed from voice)."""
    calories: Mapped[float] = mapped_column(default=0)
    protein_g: Mapped[float] = mapped_column(default=0)
    carbs_g: Mapped[float] = mapped_column(default=0)
    fat_g: Mapped[float] = mapped_column(default=0)
    is_estimated: Mapped[bool] = mapped_column(default=True)
    """True when macros were estimated by the LLM rather than entered exactly."""
    source: Mapped[EntrySource] = mapped_column(
        pg_enum(EntrySource, "entry_source"), default=EntrySource.MANUAL
    )

    user: Mapped["User"] = relationship(back_populates="nutrition_logs")
