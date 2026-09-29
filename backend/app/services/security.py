"""Password hashing and JWT helpers."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

BCRYPT_MAX_PASSWORD_BYTES = 72
"""bcrypt only uses the first 72 bytes; bcrypt>=5 raises instead of truncating."""


def hash_password(password: str) -> str:
    """Return a bcrypt hash of `password`."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check of `password` against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:  # malformed hash or over-long password
        return False


# Used to spend the same bcrypt time when an email is unknown, so login response
# timing does not reveal which emails are registered.
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing")


def create_access_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    """Issue a signed JWT with `sub=user_id` and an `exp` claim."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": str(user_id), "iat": now, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Validate a JWT and return the user id. Raises `jwt.InvalidTokenError` on failure."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp"]},
    )
    try:
        return uuid.UUID(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise jwt.InvalidTokenError("Invalid subject claim") from exc
