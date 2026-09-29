"""Monthly progress report generation."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models import ProgressReport


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def compute_metrics(self, user_id: uuid.UUID, start: date, end: date) -> dict[str, Any]:
        """Aggregate the period's data.

        Includes: sessions planned vs. completed (adherence), total volume, PRs / e1RM changes
        per lift, average daily calories & macros vs. targets, body-weight trend, and count of
        safety events.
        """
        raise NotImplementedError

    def generate(self, user_id: uuid.UUID, start: date | None, end: date | None) -> ProgressReport:
        """Compute metrics, have the LLM write summary + recommendations, and upsert the report.

        Defaults to the previous calendar month when no period is given.
        """
        raise NotImplementedError
