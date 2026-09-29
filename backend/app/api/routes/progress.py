"""Body metrics, progress overviews (chart data) and monthly progress reports."""

import uuid
from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.models import BodyMetric, ProgressReport
from app.schemas import (
    BodyMetricCreate,
    BodyMetricRead,
    ProgressOverview,
    ProgressReportGenerateRequest,
    ProgressReportRead,
    ProgressReportSummary,
)
from app.services.report_service import ReportGenerationError, ReportService

router = APIRouter(prefix="/progress", tags=["progress"])


def get_report_service(db: DbSession) -> ReportService:
    return ReportService(db)


Reports = Annotated[ReportService, Depends(get_report_service)]


@router.post("/metrics", response_model=BodyMetricRead, status_code=status.HTTP_201_CREATED)
def record_metric(payload: BodyMetricCreate, user: CurrentUser, reports: Reports) -> BodyMetric:
    """Record a body measurement (weight, body fat, etc.). The latest weight also updates the profile."""
    return reports.record_metric(user, **payload.model_dump())


@router.get("/metrics", response_model=list[BodyMetricRead])
def list_metrics(
    user: CurrentUser, reports: Reports, start: date | None = None, end: date | None = None
) -> list[BodyMetric]:
    return reports.list_metrics(user.id, start, end)


@router.get("/overview", response_model=ProgressOverview)
def overview(
    user: CurrentUser,
    reports: Reports,
    start: date,
    end: date,
    tz: str = Query("UTC", max_length=64, description="IANA timezone defining calendar days"),
) -> ProgressOverview:
    """Chart-ready progress data for a period (no LLM): training, strength curves, calories,
    body weight, and flags."""
    if end < start or (end - start).days > 366:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="end must be after start, and the period at most a year")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown timezone: {tz!r}") from None
    return reports.overview(user, start, end, tz)


@router.post("/reports", response_model=ProgressReportRead, status_code=status.HTTP_201_CREATED)
def generate_report(payload: ProgressReportGenerateRequest, user: CurrentUser, reports: Reports) -> ProgressReport:
    """Compute metrics for the period and have the LLM write the narrative report.

    Idempotent per (user, period_start): regenerating replaces the existing report.
    """
    try:
        return reports.generate(user, payload.period_start, payload.period_end, payload.timezone)
    except ReportGenerationError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Couldn't write the report right now. Please try again.") from None


@router.get("/reports", response_model=list[ProgressReportSummary])
def list_reports(user: CurrentUser, reports: Reports) -> list[ProgressReport]:
    return reports.list_reports(user.id)


@router.get("/reports/{report_id}", response_model=ProgressReportRead)
def get_report(report_id: uuid.UUID, user: CurrentUser, reports: Reports) -> ProgressReport:
    report = reports.get_report(user.id, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report
