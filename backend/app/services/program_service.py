"""Personalized training program generation and lifecycle."""

import uuid

from sqlalchemy.orm import Session

from app.models import TrainingProgram, User
from app.schemas import ProgramGenerateRequest, ProgramUpdate


class ProgramService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate(self, user: User, request: ProgramGenerateRequest) -> TrainingProgram:
        """Build and persist a new program.

        Steps: load profile -> retrieve programming guidelines from RAG -> ask the LLM for a
        structured plan (validated against `ProgramWorkoutCreate`) -> map exercise names to
        library IDs, excluding contraindicated movements -> save as DRAFT.
        """
        raise NotImplementedError

    def get_active(self, user_id: uuid.UUID) -> TrainingProgram | None:
        raise NotImplementedError

    def activate(self, program: TrainingProgram) -> TrainingProgram:
        """Mark `program` ACTIVE and archive any other active program for the user."""
        raise NotImplementedError

    def update(self, program: TrainingProgram, changes: ProgramUpdate) -> TrainingProgram:
        raise NotImplementedError

    def current_week_number(self, program: TrainingProgram) -> int:
        """Week index (1-based) of today within the program, clamped to its duration."""
        raise NotImplementedError
