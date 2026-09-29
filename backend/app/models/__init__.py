"""SQLAlchemy ORM models.

Every model is imported here so that `Base.metadata` is fully populated (needed by
`create_all`, Alembic autogenerate, and string-based relationship resolution).
"""

from app.models.base import Base
from app.models.conversation import Conversation, Message
from app.models.exercise import Exercise
from app.models.nutrition import NutritionLog
from app.models.program import PlannedExercise, ProgramWorkout, TrainingProgram
from app.models.progress import BodyMetric, ProgressReport
from app.models.safety import SafetyEvent
from app.models.user import User, UserProfile
from app.models.workout import ExerciseSet, WorkoutSession

__all__ = [
    "Base",
    "BodyMetric",
    "Conversation",
    "Exercise",
    "ExerciseSet",
    "Message",
    "NutritionLog",
    "PlannedExercise",
    "ProgramWorkout",
    "ProgressReport",
    "SafetyEvent",
    "TrainingProgram",
    "User",
    "UserProfile",
    "WorkoutSession",
]
