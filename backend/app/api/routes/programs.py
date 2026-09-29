"""Training program generation and management."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import ProgramGenerateRequest, ProgramRead, ProgramSummary, ProgramUpdate, ProgramWorkoutRead

router = APIRouter(prefix="/programs", tags=["programs"])


@router.post("/generate", response_model=ProgramRead, status_code=status.HTTP_201_CREATED)
def generate_program(payload: ProgramGenerateRequest, user: CurrentUser, db: DbSession) -> ProgramRead:
    """Generate a personalized multi-week program via the LLM + RAG knowledge base.

    Requires a completed profile. Respects injuries/equipment/schedule, and is blocked by
    the safety layer when the profile indicates an unresolved high-severity concern.
    """
    raise NotImplementedError


@router.get("", response_model=list[ProgramSummary])
def list_programs(user: CurrentUser, db: DbSession) -> list[ProgramSummary]:
    """List the user's programs, newest first."""
    raise NotImplementedError


@router.get("/active", response_model=ProgramRead)
def get_active_program(user: CurrentUser, db: DbSession) -> ProgramRead:
    """Return the currently active program. 404 if none."""
    raise NotImplementedError


@router.get("/active/this-week", response_model=list[ProgramWorkoutRead])
def get_this_week(user: CurrentUser, db: DbSession) -> list[ProgramWorkoutRead]:
    """Planned workouts for the current week of the active program."""
    raise NotImplementedError


@router.get("/{program_id}", response_model=ProgramRead)
def get_program(program_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProgramRead:
    """Return one program with all weeks, workouts, and exercises."""
    raise NotImplementedError


@router.patch("/{program_id}", response_model=ProgramRead)
def update_program(
    program_id: uuid.UUID, payload: ProgramUpdate, user: CurrentUser, db: DbSession
) -> ProgramRead:
    """Rename, annotate, or change status (activating one program archives the previous)."""
    raise NotImplementedError


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(program_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Delete a program. Logged sessions are kept (their link is nulled)."""
    raise NotImplementedError
