"""Current-user account and fitness profile."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import User, UserProfile
from app.schemas import (
    SafetyNotice,
    UserProfileCreate,
    UserProfileRead,
    UserProfileUpdate,
    UserRead,
    UserUpdate,
)
from app.services.safety_service import SafetyService
from app.services.security import hash_password

router = APIRouter(prefix="/users/me", tags=["users"])

PROFILE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found; complete onboarding first"
)


@router.get("", response_model=UserRead)
def read_me(user: CurrentUser) -> User:
    """Return the authenticated user's account."""
    return user


@router.patch("", response_model=UserRead)
def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> User:
    """Update name and/or password."""
    changes = payload.model_dump(exclude_unset=True)
    if "full_name" in changes:
        user.full_name = changes["full_name"]
    if changes.get("password") is not None:
        user.hashed_password = hash_password(changes["password"])
    db.commit()
    db.refresh(user)
    return user


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: CurrentUser, db: DbSession) -> None:
    """Delete the account and all associated data (cascades)."""
    db.delete(user)
    db.commit()


@router.get("/profile", response_model=UserProfileRead)
def read_profile(user: CurrentUser) -> UserProfileRead:
    """Return the fitness profile (with any standing safety notice). 404 if onboarding not completed."""
    if user.profile is None:
        raise PROFILE_NOT_FOUND
    response = UserProfileRead.model_validate(user.profile)
    assessment = SafetyService.screen_profile_static(user.profile)
    if assessment.is_flagged:
        response.safety_notice = SafetyNotice(
            category=assessment.category, severity=assessment.severity,
            action_taken=assessment.recommended_action, message=assessment.user_facing_message or "")
    return response


@router.put("/profile", response_model=UserProfileRead)
def create_or_replace_profile(
    payload: UserProfileCreate, user: CurrentUser, db: DbSession
) -> UserProfileRead:
    """Create the profile during onboarding (or fully replace it).

    Fields omitted from the payload are reset to their defaults. Health answers are screened;
    the response carries a `safety_notice` when they call for caution or medical clearance.
    """
    before = _health_text(user.profile)
    data = payload.model_dump()
    if user.profile is None:
        user.profile = UserProfile(**data)
    else:
        for field, value in data.items():
            setattr(user.profile, field, value)
    return _save_and_screen(user, db, before)


@router.patch("/profile", response_model=UserProfileRead)
def update_profile(payload: UserProfileUpdate, user: CurrentUser, db: DbSession) -> UserProfileRead:
    """Partially update the profile."""
    if user.profile is None:
        raise PROFILE_NOT_FOUND
    before = _health_text(user.profile)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user.profile, field, value)
    return _save_and_screen(user, db, before)


def _health_text(profile: UserProfile | None) -> tuple:
    if profile is None:
        return (None, None, None)
    return (profile.injuries, profile.medical_conditions, profile.medical_clearance)


def _save_and_screen(user: User, db: DbSession, before: tuple) -> UserProfileRead:
    """Commit the profile, screen its health answers, and log a SafetyEvent if they changed."""
    safety = SafetyService(db)
    assessment = safety.screen_profile(user.profile)
    if assessment.is_flagged and _health_text(user.profile) != before:
        safety.record_event(user.id, assessment, " | ".join(
            filter(None, [user.profile.injuries, user.profile.medical_conditions])))
    db.commit()
    db.refresh(user.profile)
    response = UserProfileRead.model_validate(user.profile)
    if assessment.is_flagged:
        response.safety_notice = SafetyNotice(
            category=assessment.category, severity=assessment.severity,
            action_taken=assessment.recommended_action, message=assessment.user_facing_message or "")
    return response
