"""Schemas for users, authentication, and fitness profiles."""

from datetime import date

from pydantic import EmailStr, Field

from app.models.enums import FitnessGoal, FitnessLevel, Sex
from app.schemas.common import CoachinSchema, TimestampedReadSchema

# --- Auth ------------------------------------------------------------------


class UserCreate(CoachinSchema):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class LoginRequest(CoachinSchema):
    email: EmailStr
    password: str


class Token(CoachinSchema):
    access_token: str
    token_type: str = "bearer"


class UserRead(TimestampedReadSchema):
    email: EmailStr
    full_name: str | None
    is_active: bool


class UserUpdate(CoachinSchema):
    full_name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)


# --- Profile ---------------------------------------------------------------


class UserProfileBase(CoachinSchema):
    date_of_birth: date | None = None
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, gt=50, lt=300)
    weight_kg: float | None = Field(default=None, gt=20, lt=400)

    fitness_level: FitnessLevel = FitnessLevel.BEGINNER
    primary_goal: FitnessGoal = FitnessGoal.GENERAL_FITNESS
    training_days_per_week: int = Field(default=3, ge=1, le=7)
    session_duration_min: int = Field(default=60, ge=10, le=240)
    available_equipment: list[str] = Field(default_factory=list)

    injuries: str | None = None
    medical_conditions: str | None = None
    medical_clearance: bool = False

    dietary_preferences: list[str] = Field(default_factory=list)
    daily_calorie_target: int | None = Field(default=None, ge=800, le=10000)
    daily_protein_target_g: int | None = Field(default=None, ge=0)
    daily_carbs_target_g: int | None = Field(default=None, ge=0)
    daily_fat_target_g: int | None = Field(default=None, ge=0)

    preferred_tts_voice: str | None = None


class UserProfileCreate(UserProfileBase):
    """Payload for onboarding; all training fields have sensible defaults."""


class UserProfileUpdate(CoachinSchema):
    """Partial update; only provided fields are changed."""

    date_of_birth: date | None = None
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, gt=50, lt=300)
    weight_kg: float | None = Field(default=None, gt=20, lt=400)
    fitness_level: FitnessLevel | None = None
    primary_goal: FitnessGoal | None = None
    training_days_per_week: int | None = Field(default=None, ge=1, le=7)
    session_duration_min: int | None = Field(default=None, ge=10, le=240)
    available_equipment: list[str] | None = None
    injuries: str | None = None
    medical_conditions: str | None = None
    medical_clearance: bool | None = None
    dietary_preferences: list[str] | None = None
    daily_calorie_target: int | None = Field(default=None, ge=800, le=10000)
    daily_protein_target_g: int | None = Field(default=None, ge=0)
    daily_carbs_target_g: int | None = Field(default=None, ge=0)
    daily_fat_target_g: int | None = Field(default=None, ge=0)
    preferred_tts_voice: str | None = None


class UserProfileRead(TimestampedReadSchema, UserProfileBase):
    pass
