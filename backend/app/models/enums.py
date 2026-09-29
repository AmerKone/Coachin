"""Enumerations shared by ORM models and Pydantic schemas."""

from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class FitnessLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class FitnessGoal(StrEnum):
    FAT_LOSS = "fat_loss"
    MUSCLE_GAIN = "muscle_gain"
    STRENGTH = "strength"
    ENDURANCE = "endurance"
    GENERAL_FITNESS = "general_fitness"


class ProgramStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MuscleGroup(StrEnum):
    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    QUADRICEPS = "quadriceps"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    CALVES = "calves"
    CORE = "core"
    FULL_BODY = "full_body"
    CARDIO = "cardio"


class ExerciseCategory(StrEnum):
    COMPOUND = "compound"
    ISOLATION = "isolation"
    CARDIO = "cardio"
    MOBILITY = "mobility"


class Equipment(StrEnum):
    """Equipment an exercise requires. An exercise needing none has an empty list."""

    BARBELL = "barbell"
    DUMBBELLS = "dumbbells"
    KETTLEBELLS = "kettlebells"
    SQUAT_RACK = "squat rack"
    BENCH = "bench"
    PULL_UP_BAR = "pull-up bar"
    DIP_BARS = "dip bars"
    RESISTANCE_BANDS = "resistance bands"
    CABLE_MACHINE = "cable machine"
    MACHINES = "machines"
    """Plate-loaded or selectorized gym machines (leg press, leg curl, ...)."""
    CARDIO_MACHINE = "cardio machine"
    """Treadmill, bike, rower, etc."""


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class EntrySource(StrEnum):
    """How a log entry was captured."""

    MANUAL = "manual"
    VOICE = "voice"
    AGENT = "agent"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class SafetyCategory(StrEnum):
    CARDIOVASCULAR = "cardiovascular"      # chest pain, fainting, palpitations
    INJURY = "injury"
    MEDICAL_CONDITION = "medical_condition"
    MEDICATION = "medication"
    PREGNANCY = "pregnancy"
    EATING_DISORDER = "eating_disorder"
    MENTAL_HEALTH = "mental_health"
    EXTREME_DIETING = "extreme_dieting"
    OTHER = "other"


class SafetySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SafetyAction(StrEnum):
    """What the guardrail did in response to a detected concern."""

    LOGGED = "logged"              # noted, conversation continued normally
    CAUTIONED = "cautioned"        # response included a caution / modification
    REFERRED = "referred"          # advised to consult a professional
    BLOCKED = "blocked"            # coaching refused for this request
    EMERGENCY = "emergency"        # emergency-services guidance given
