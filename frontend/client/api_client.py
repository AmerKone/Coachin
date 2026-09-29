"""Typed-ish wrapper over the backend REST API.

Returns plain dicts (JSON) so the frontend does not depend on backend packages.
"""

from datetime import date
from typing import Any

import httpx

from config import API_BASE, REQUEST_TIMEOUT_SECONDS

GENERATION_TIMEOUT_SECONDS = 240.0


class ApiError(Exception):
    """Raised for non-2xx responses; carries the status code and backend `detail`."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _format_detail(detail: Any) -> str:
    """Flatten FastAPI error details (a string, or a list of validation errors)."""
    if isinstance(detail, list):
        messages = []
        for err in detail:
            field = ".".join(str(part) for part in err.get("loc", [])[1:])  # drop "body"/"query"
            msg = err.get("msg", "Invalid value").removeprefix("Value error, ")
            messages.append(f"{field}: {msg}" if field else msg)
        return "; ".join(messages)
    return str(detail)


class CoachinClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self._http = httpx.Client(base_url=API_BASE, timeout=REQUEST_TIMEOUT_SECONDS)

    # Auth
    def register(self, email: str, password: str, full_name: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/auth/register", json={"email": email, "password": password, "full_name": full_name})

    def login(self, email: str, password: str) -> str:
        """Return an access token and store it on the client."""
        data = self._request("POST", "/auth/login", data={"username": email, "password": password})
        self.token = data["access_token"]
        return self.token

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/users/me")

    def update_me(self, changes: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", "/users/me", json=changes)

    # Profile
    def get_profile(self) -> dict[str, Any] | None:
        """Return the profile, or None if the user hasn't completed onboarding."""
        try:
            return self._request("GET", "/users/me/profile")
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def save_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", "/users/me/profile", json=profile)

    # Chat & voice
    def chat(self, message: str, conversation_id: str | None = None, speak: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    def voice_chat(self, audio_bytes: bytes, filename: str, conversation_id: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    # Programs
    def generate_program(self, request: dict[str, Any]) -> dict[str, Any]:
        """Ask the coach to design a program (an LLM call: can take up to a minute or two)."""
        return self._request("POST", "/programs/generate", json=request, timeout=GENERATION_TIMEOUT_SECONDS)

    def list_programs(self) -> list[dict[str, Any]]:
        return self._request("GET", "/programs")

    def get_program(self, program_id: str) -> dict[str, Any]:
        return self._request("GET", f"/programs/{program_id}")

    def get_active_program(self) -> dict[str, Any] | None:
        try:
            return self._request("GET", "/programs/active")
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def update_program(self, program_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/programs/{program_id}", json=changes)

    def delete_program(self, program_id: str) -> None:
        self._request("DELETE", f"/programs/{program_id}")

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
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.is_error:
            try:
                detail = _format_detail(response.json().get("detail", response.text))
            except ValueError:
                detail = response.text or response.reason_phrase
            raise ApiError(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()
