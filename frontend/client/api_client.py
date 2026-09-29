"""Typed-ish wrapper over the backend REST API.

Returns plain dicts (JSON) so the frontend does not depend on backend packages.
"""

from datetime import date
from typing import Any

import httpx

from config import API_BASE, REQUEST_TIMEOUT_SECONDS


class ApiError(Exception):
    """Raised for non-2xx responses; carries the status code and backend `detail`."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class CoachinClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self._http = httpx.Client(base_url=API_BASE, timeout=REQUEST_TIMEOUT_SECONDS)

    # Auth
    def register(self, email: str, password: str, full_name: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def login(self, email: str, password: str) -> str:
        """Return an access token and store it on the client."""
        raise NotImplementedError

    # Profile
    def get_profile(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def save_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    # Chat & voice
    def chat(self, message: str, conversation_id: str | None = None, speak: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    def voice_chat(self, audio_bytes: bytes, filename: str, conversation_id: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    # Programs
    def generate_program(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def get_active_program(self) -> dict[str, Any] | None:
        raise NotImplementedError

    # Workouts
    def log_workout(self, session: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def next_targets(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def exercise_history(self, exercise_id: str, weeks: int = 12) -> list[dict[str, Any]]:
        raise NotImplementedError

    # Nutrition
    def estimate_meal(self, description: str, meal_type: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def daily_nutrition(self, day: date) -> dict[str, Any]:
        raise NotImplementedError

    # Progress
    def record_metric(self, metric: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def list_reports(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def generate_report(self, period_start: date | None = None, period_end: date | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send a request with the bearer token; raise `ApiError` on failure, return JSON."""
        raise NotImplementedError
