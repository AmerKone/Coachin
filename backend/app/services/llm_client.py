"""Thin wrapper around the OpenAI SDK shared by all services."""

from functools import lru_cache
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.config import get_settings

M = TypeVar("M", bound=BaseModel)


@lru_cache
def get_openai_client() -> OpenAI:
    """Return a process-wide OpenAI client configured from settings."""
    return OpenAI(api_key=get_settings().openai_api_key)


def complete(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.4,
) -> Any:
    """Run a chat completion with retries; returns the raw SDK response."""
    raise NotImplementedError


def complete_structured(messages: list[dict[str, Any]], schema: type[M]) -> M:
    """Run a chat completion constrained to `schema` (structured outputs) and parse it."""
    raise NotImplementedError
