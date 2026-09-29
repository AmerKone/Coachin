"""Registration and login."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.models import User
from app.schemas import Token, UserCreate, UserRead
from app.services.security import DUMMY_PASSWORD_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_TAKEN = HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: DbSession) -> User:
    """Create a new account. Returns 409 if the email is already registered."""
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise EMAIL_TAKEN

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # concurrent registration with the same email
        db.rollback()
        raise EMAIL_TAKEN from None
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """Exchange email (as `username`) + password for a JWT access token."""
    user = db.scalar(select(User).where(User.email == form.username.strip().lower()))

    # Always run bcrypt so response time doesn't reveal whether the email exists.
    password_ok = verify_password(form.password, user.hashed_password if user else DUMMY_PASSWORD_HASH)
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))
