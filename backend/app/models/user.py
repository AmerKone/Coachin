"""User account and fitness profile models."""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import FitnessGoal, FitnessLevel, Sex

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.nutrition import NutritionLog
    from app.models.program import TrainingProgram
    from app.models.progress import BodyMetric, ProgressReport
    from app.models.safety import SafetyEvent
    from app.models.workout import WorkoutSession


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated Coachin user."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(default=True)

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    programs: Mapped[list["TrainingProgram"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workout_sessions: Mapped[list["WorkoutSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    nutrition_logs: Mapped[list["NutritionLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    body_metrics: Mapped[list["BodyMetric"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    progress_reports: Mapped[list["ProgressReport"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    safety_events: Mapped[list["SafetyEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fitness profile used to personalize programs and nutrition targets.

    One-to-one with `User`. Health fields (`injuries`, `medical_conditions`) feed the
    safety guardrails and the program generator's exercise exclusions.
    """

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint("training_days_per_week BETWEEN 1 AND 7", name="ck_profile_training_days"),
        CheckConstraint("session_duration_min BETWEEN 10 AND 240", name="ck_profile_session_duration"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    # Demographics / anthropometrics
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[Sex | None] = mapped_column(pg_enum(Sex, "sex"))
    height_cm: Mapped[float | None]
    weight_kg: Mapped[float | None]

    # Training preferences
    fitness_level: Mapped[FitnessLevel] = mapped_column(
        pg_enum(FitnessLevel, "fitness_level"), default=FitnessLevel.BEGINNER
    )
    primary_goal: Mapped[FitnessGoal] = mapped_column(
        pg_enum(FitnessGoal, "fitness_goal"), default=FitnessGoal.GENERAL_FITNESS
    )
    training_days_per_week: Mapped[int] = mapped_column(default=3)
    session_duration_min: Mapped[int] = mapped_column(default=60)
    available_equipment: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Health & safety context
    injuries: Mapped[str | None] = mapped_column(Text)
    medical_conditions: Mapped[str | None] = mapped_column(Text)
    medical_clearance: Mapped[bool] = mapped_column(default=False)

    # Nutrition
    dietary_preferences: Mapped[list[str]] = mapped_column(JSON, default=list)
    daily_calorie_target: Mapped[int | None]
    daily_protein_target_g: Mapped[int | None]
    daily_carbs_target_g: Mapped[int | None]
    daily_fat_target_g: Mapped[int | None]

    # Voice preferences
    preferred_tts_voice: Mapped[str | None] = mapped_column(String(32))

    user: Mapped["User"] = relationship(back_populates="profile")
