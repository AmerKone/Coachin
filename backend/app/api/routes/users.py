"""Current-user account and fitness profile."""

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import UserProfileCreate, UserProfileRead, UserProfileUpdate, UserRead, UserUpdate

router = APIRouter(prefix="/users/me", tags=["users"])


@router.get("", response_model=UserRead)
def read_me(user: CurrentUser) -> UserRead:
    """Return the authenticated user's account."""
    raise NotImplementedError


@router.patch("", response_model=UserRead)
def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> UserRead:
    """Update name and/or password."""
    raise NotImplementedError


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: CurrentUser, db: DbSession) -> None:
    """Delete the account and all associated data (cascades)."""
    raise NotImplementedError


@router.get("/profile", response_model=UserProfileRead)
def read_profile(user: CurrentUser) -> UserProfileRead:
    """Return the fitness profile. 404 if onboarding not completed."""
    raise NotImplementedError


@router.put("/profile", response_model=UserProfileRead)
def create_or_replace_profile(
    payload: UserProfileCreate, user: CurrentUser, db: DbSession
) -> UserProfileRead:
    """Create the profile during onboarding (or fully replace it).

    Runs the safety screen over `injuries` / `medical_conditions` and may compute default
    macro targets when none are supplied.
    """
    raise NotImplementedError


@router.patch("/profile", response_model=UserProfileRead)
def update_profile(payload: UserProfileUpdate, user: CurrentUser, db: DbSession) -> UserProfileRead:
    """Partially update the profile."""
    raise NotImplementedError
