"""Declarative base and shared column mixins for all ORM models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every Coachin model."""


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key generated client-side."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Adds server-managed `created_at` / `updated_at` columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Build a PostgreSQL ENUM type that stores the enum *values* (not member names)."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])
