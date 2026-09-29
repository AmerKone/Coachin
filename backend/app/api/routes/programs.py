"""Training program generation and management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.models import ProgramWorkout, TrainingProgram
from app.schemas import ProgramGenerateRequest, ProgramRead, ProgramSummary, ProgramUpdate, ProgramWorkoutRead
from app.services.program_service import ProfileRequiredError, ProgramGenerationError, ProgramService

router = APIRouter(prefix="/programs", tags=["programs"])


def get_program_service(db: DbSession) -> ProgramService:
    return ProgramService(db)


Programs = Annotated[ProgramService, Depends(get_program_service)]


def _get_owned(programs: ProgramService, user_id: uuid.UUID, program_id: uuid.UUID) -> TrainingProgram:
    program = programs.get(user_id, program_id)
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")
    return program


@router.post("/generate", response_model=ProgramRead, status_code=status.HTTP_201_CREATED)
def generate_program(payload: ProgramGenerateRequest, user: CurrentUser, programs: Programs) -> TrainingProgram:
    """Generate a personalized multi-week program with the LLM, saved as a draft.

    Requires a completed profile. Uses only exercises the user's equipment allows and
    avoids exercises that conflict with reported injuries.
    """
    try:
        return programs.generate(user, payload)
    except ProfileRequiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Complete your profile before generating a program"
        ) from None
    except ProgramGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not generate a program: {exc}"
        ) from None


@router.get("", response_model=list[ProgramSummary])
def list_programs(user: CurrentUser, programs: Programs) -> list[TrainingProgram]:
    """List the user's programs, newest first."""
    return programs.list_for_user(user.id)


@router.get("/active", response_model=ProgramRead)
def get_active_program(user: CurrentUser, programs: Programs) -> TrainingProgram:
    """Return the currently active program. 404 if none."""
    program = programs.get_active(user.id)
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program")
    return program


@router.get("/active/this-week", response_model=list[ProgramWorkoutRead])
def get_this_week(user: CurrentUser, programs: Programs) -> list[ProgramWorkout]:
    """Planned workouts for the current week of the active program."""
    program = programs.get_active(user.id)
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program")
    return programs.this_week(program)


@router.get("/{program_id}", response_model=ProgramRead)
def get_program(program_id: uuid.UUID, user: CurrentUser, programs: Programs) -> TrainingProgram:
    """Return one program with all weeks, workouts, and exercises."""
    return _get_owned(programs, user.id, program_id)


@router.patch("/{program_id}", response_model=ProgramRead)
def update_program(
    program_id: uuid.UUID, payload: ProgramUpdate, user: CurrentUser, programs: Programs
) -> TrainingProgram:
    """Rename, annotate, or change status (activating one program archives the previous)."""
    program = _get_owned(programs, user.id, program_id)
    programs.update(program, payload)
    return _get_owned(programs, user.id, program_id)


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_program(program_id: uuid.UUID, user: CurrentUser, programs: Programs) -> None:
    """Delete a program. Logged sessions are kept (their link is nulled)."""
    programs.delete(_get_owned(programs, user.id, program_id))
