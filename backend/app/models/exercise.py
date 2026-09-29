"""Exercise library model."""

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enums import ExerciseCategory, MuscleGroup


class Exercise(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A movement that can be prescribed in a program and logged in a session."""

    __tablename__ = "exercises"

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    primary_muscle: Mapped[MuscleGroup] = mapped_column(pg_enum(MuscleGroup, "muscle_group"))
    secondary_muscles: Mapped[list[str]] = mapped_column(JSON, default=list)
    category: Mapped[ExerciseCategory] = mapped_column(pg_enum(ExerciseCategory, "exercise_category"))
    equipment: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_bodyweight: Mapped[bool] = mapped_column(default=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    contraindications: Mapped[str | None] = mapped_column(Text)
    """Free-text notes on conditions/injuries for which this exercise should be avoided."""
