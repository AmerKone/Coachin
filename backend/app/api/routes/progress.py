"""Body metrics and monthly progress reports."""

import uuid
from datetime import date

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas import (
    BodyMetricCreate,
    BodyMetricRead,
    ProgressReportGenerateRequest,
    ProgressReportRead,
    ProgressReportSummary,
)

router = APIRouter(prefix="/progress", tags=["progress"])


@router.post("/metrics", response_model=BodyMetricRead, status_code=status.HTTP_201_CREATED)
def record_metric(payload: BodyMetricCreate, user: CurrentUser, db: DbSession) -> BodyMetricRead:
    """Record a body measurement (weight, body fat, etc.)."""
    raise NotImplementedError


@router.get("/metrics", response_model=list[BodyMetricRead])
def list_metrics(
    user: CurrentUser, db: DbSession, start: date | None = None, end: date | None = None
) -> list[BodyMetricRead]:
    raise NotImplementedError


@router.post("/reports", response_model=ProgressReportRead, status_code=status.HTTP_201_CREATED)
def generate_report(
    payload: ProgressReportGenerateRequest, user: CurrentUser, db: DbSession
) -> ProgressReportRead:
    """Compute metrics for the period and have the LLM write the narrative report.

    Idempotent per (user, period_start): regenerating replaces the existing report.
    """
    raise NotImplementedError


@router.get("/reports", response_model=list[ProgressReportSummary])
def list_reports(user: CurrentUser, db: DbSession) -> list[ProgressReportSummary]:
    raise NotImplementedError


@router.get("/reports/{report_id}", response_model=ProgressReportRead)
def get_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProgressReportRead:
    raise NotImplementedError
