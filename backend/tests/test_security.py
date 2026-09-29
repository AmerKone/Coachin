"""Unit tests for password hashing and JWT helpers (no database needed)."""

import uuid
from datetime import timedelta

import jwt
import pytest

from app.services.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong-pass", hashed)


def test_verify_password_handles_malformed_hash() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id)) == user_id


def test_expired_token_rejected() -> None:
    token = create_access_token(uuid.uuid4(), expires_delta=timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_tampered_token_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
