"""Read-only view of the user's safety-guardrail history."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas import SafetyEventRead

router = APIRouter(prefix="/safety", tags=["safety"])


@router.get("/events", response_model=list[SafetyEventRead])
def list_safety_events(user: CurrentUser, db: DbSession) -> list[SafetyEventRead]:
    """Guardrail triggers for the current user, newest first."""
    raise NotImplementedError
