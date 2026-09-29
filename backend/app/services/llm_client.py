"""Thin wrapper around the OpenAI SDK shared by all services."""

from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings

M = TypeVar("M", bound=BaseModel)

StructuredLLM = Callable[[list[dict[str, Any]], type[M]], M]
"""Signature of `complete_structured`; services accept one so tests can inject a fake."""

_TRANSIENT_ERRORS = (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError,
                     openai.InternalServerError)


class LLMError(Exception):
    """The LLM call failed or returned an unusable response."""


@lru_cache
def get_openai_client() -> OpenAI:
    """Return a process-wide OpenAI client configured from settings."""
    return OpenAI(api_key=get_settings().openai_api_key, timeout=120, max_retries=0)


_retry = retry(
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=10),
    reraise=True,
)


@_retry
def complete(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.4,
) -> Any:
    """Run a chat completion with retries; returns the raw SDK response."""
    kwargs: dict[str, Any] = {"tools": tools} if tools else {}
    return get_openai_client().chat.completions.create(
        model=get_settings().openai_chat_model, messages=messages, temperature=temperature, **kwargs
    )


def complete_structured(messages: list[dict[str, Any]], schema: type[M]) -> M:
    """Run a chat completion constrained to `schema` (structured outputs) and parse it.

    Raises:
        LLMError: API failure after retries, refusal, or truncated/unparseable output.
    """
    try:
        completion = _parse(messages, schema)
    except openai.OpenAIError as exc:
        raise LLMError(f"OpenAI request failed: {exc}") from exc

    message = completion.choices[0].message
    if message.refusal:
        raise LLMError(f"Model refused: {message.refusal}")
    if completion.choices[0].finish_reason == "length" or message.parsed is None:
        raise LLMError("Model response was truncated or could not be parsed")
    return message.parsed


@_retry
def _parse(messages: list[dict[str, Any]], schema: type[M]) -> Any:
    return get_openai_client().chat.completions.parse(
        model=get_settings().openai_chat_model,
        messages=messages,
        response_format=schema,
        temperature=0.4,
    )
