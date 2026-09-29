"""Schemas for users, authentication, and fitness profiles."""

from typing import Annotated, ClassVar

from pydantic import AfterValidator, EmailStr, Field, PastDate, model_validator

from app.models.enums import FitnessGoal, FitnessLevel, Sex
from app.schemas.common import CoachinSchema, TimestampedReadSchema
from app.services.security import BCRYPT_MAX_PASSWORD_BYTES


def _check_password_bytes(value: str) -> str:
    if len(value.encode()) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return value


Password = Annotated[str, Field(min_length=8), AfterValidator(_check_password_bytes)]
NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]

# --- Auth ------------------------------------------------------------------


class UserCreate(CoachinSchema):
    email: NormalizedEmail
    password: Password
    full_name: str | None = Field(default=None, max_length=120)


class LoginRequest(CoachinSchema):
    email: NormalizedEmail
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
    password: Password | None = None


# --- Profile ---------------------------------------------------------------


class UserProfileBase(CoachinSchema):
    date_of_birth: PastDate | None = None
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

    NON_NULLABLE_FIELDS: ClassVar[frozenset[str]] = frozenset({
        "fitness_level",
        "primary_goal",
        "training_days_per_week",
        "session_duration_min",
        "available_equipment",
        "medical_clearance",
        "dietary_preferences",
    })

    date_of_birth: PastDate | None = None
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

    @model_validator(mode="after")
    def _reject_null_for_required_columns(self) -> "UserProfileUpdate":
        nulled = sorted(
            name
            for name in self.model_fields_set & self.NON_NULLABLE_FIELDS
            if getattr(self, name) is None
        )
        if nulled:
            raise ValueError(f"These fields cannot be null: {', '.join(nulled)}")
        return self


class UserProfileRead(TimestampedReadSchema, UserProfileBase):
    pass
