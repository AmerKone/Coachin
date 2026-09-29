"""Password hashing and JWT helpers."""

import uuid
from datetime import timedelta

import bcrypt  # noqa: F401
import jwt  # noqa: F401

from app.config import get_settings  # noqa: F401


def hash_password(password: str) -> str:
    """Return a bcrypt hash of `password`."""
    raise NotImplementedError


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of `password` against a stored bcrypt hash."""
    raise NotImplementedError


def create_access_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    """Issue a signed JWT with `sub=user_id` and an `exp` claim."""
    raise NotImplementedError


def decode_access_token(token: str) -> uuid.UUID:
    """Validate a JWT and return the user id. Raises `jwt.InvalidTokenError` on failure."""
    raise NotImplementedError
