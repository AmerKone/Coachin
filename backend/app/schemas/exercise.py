"""Schemas for the exercise library."""

from pydantic import Field

from app.models.enums import Equipment, ExerciseCategory, MuscleGroup
from app.schemas.common import CoachinSchema, ORMReadSchema


class ExerciseBase(CoachinSchema):
    name: str = Field(min_length=1, max_length=120)
    primary_muscle: MuscleGroup
    secondary_muscles: list[MuscleGroup] = Field(default_factory=list)
    category: ExerciseCategory
    equipment: list[Equipment] = Field(default_factory=list)
    """All equipment required; empty means no equipment needed."""
    is_bodyweight: bool = False
    """True when the user's body weight is the main load (push-up, pull-up)."""
    instructions: str | None = None
    contraindications: str | None = None


class ExerciseCreate(ExerciseBase):
    pass


class ExerciseRead(ORMReadSchema, ExerciseBase):
    pass


class ExerciseSummary(ORMReadSchema):
    """Compact form embedded in program and workout responses."""

    name: str
    primary_muscle: MuscleGroup
    category: ExerciseCategory
