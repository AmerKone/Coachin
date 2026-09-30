"""Registration and login."""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.models import User
from app.schemas import Token, UserCreate, UserRead
from app.services.rate_limit import login_failures_by_account, login_failures_by_ip
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
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DbSession) -> Token:
    """Exchange email (as `username`) + password for a JWT access token.

    Rate limited: after 5 failed attempts for one account from one address (or 20 from one
    address overall) within 15 minutes, logins return 429 until the window passes, even with the
    right password, so guesses can't be confirmed.
    """
    email = form.username.strip().lower()
    client_ip = request.client.host if request.client else "unknown"
    account_key, ip_key = f"{email}|{client_ip}", client_ip

    wait = max(login_failures_by_account.retry_after(account_key), login_failures_by_ip.retry_after(ip_key))
    if wait > 0:
        minutes = max(1, math.ceil(wait / 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Please try again in {minutes} minute{'s' if minutes > 1 else ''}.",
            headers={"Retry-After": str(math.ceil(wait))},
        )

    user = db.scalar(select(User).where(User.email == email))
    # Always run bcrypt so response time doesn't reveal whether the email exists.
    password_ok = verify_password(form.password, user.hashed_password if user else DUMMY_PASSWORD_HASH)
    if user is None or not password_ok or not user.is_active:
        login_failures_by_account.record_failure(account_key)
        login_failures_by_ip.record_failure(ip_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    login_failures_by_account.reset(account_key)
    return Token(access_token=create_access_token(user.id))
