"""Shared Pydantic base classes and generic response shapes."""

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class CoachinSchema(BaseModel):
    """Base schema: strips whitespace and forbids unknown fields on input."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ORMReadSchema(BaseModel):
    """Base for response schemas built from ORM objects."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class TimestampedReadSchema(ORMReadSchema):
    created_at: datetime
    updated_at: datetime


class Page(BaseModel, Generic[T]):
    """Generic paginated list response."""

    items: list[T]
    total: int
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class Message(BaseModel):
    """Simple informational response, e.g. `{"detail": "deleted"}`."""

    detail: str
