"""Read-only view of the user's safety-guardrail history."""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import SafetyEvent
from app.schemas import SafetyEventRead

router = APIRouter(prefix="/safety", tags=["safety"])


@router.get("/events", response_model=list[SafetyEventRead])
def list_safety_events(user: CurrentUser, db: DbSession) -> list[SafetyEvent]:
    """Guardrail triggers for the current user, newest first."""
    return list(db.scalars(
        select(SafetyEvent).where(SafetyEvent.user_id == user.id).order_by(SafetyEvent.created_at.desc()).limit(200)
    ))
