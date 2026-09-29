"""Current-user account and fitness profile."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import User, UserProfile
from app.schemas import UserProfileCreate, UserProfileRead, UserProfileUpdate, UserRead, UserUpdate
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
def read_profile(user: CurrentUser) -> UserProfile:
    """Return the fitness profile. 404 if onboarding not completed."""
    if user.profile is None:
        raise PROFILE_NOT_FOUND
    return user.profile


@router.put("/profile", response_model=UserProfileRead)
def create_or_replace_profile(
    payload: UserProfileCreate, user: CurrentUser, db: DbSession
) -> UserProfile:
    """Create the profile during onboarding (or fully replace it).

    Fields omitted from the payload are reset to their defaults.
    """
    # TODO: run SafetyService.screen_profile over injuries/medical_conditions once implemented.
    data = payload.model_dump()
    if user.profile is None:
        user.profile = UserProfile(**data)
    else:
        for field, value in data.items():
            setattr(user.profile, field, value)
    db.commit()
    db.refresh(user.profile)
    return user.profile


@router.patch("/profile", response_model=UserProfileRead)
def update_profile(payload: UserProfileUpdate, user: CurrentUser, db: DbSession) -> UserProfile:
    """Partially update the profile."""
    if user.profile is None:
        raise PROFILE_NOT_FOUND
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user.profile, field, value)
    db.commit()
    db.refresh(user.profile)
    return user.profile
