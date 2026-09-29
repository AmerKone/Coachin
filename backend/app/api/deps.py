"""Shared FastAPI dependencies (DB session, authenticated user, service factories)."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """Decode the bearer JWT and load the active user.

    Raises:
        HTTPException(401): token missing, invalid, expired, or user inactive.
    """
    raise NotImplementedError


CurrentUser = Annotated[User, Depends(get_current_user)]
