from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import ModerationStatusEnum, ReportStatusEnum, ReportTypeEnum

__all__ = [
    "AdminReportDetailOutput",
    "AdminReportItemOutput",
    "AdminReportPreviousReportsOutput",
    "AdminReportResolutionOutput",
    "AdminReportTargetOutput",
    "AdminReportUserOutput",
    "AdminReportsOutput",
]


class AdminReportUserOutput(BaseModel):
    id: UUID
    name: str | None


class AdminReportTargetOutput(BaseModel):
    type: Literal["USER", "BUSINESS", "EVENT"]
    id: UUID
    name: str | None
    member_since: date
    event_count: int
    moderation_status: ModerationStatusEnum


class AdminReportPreviousReportsOutput(BaseModel):
    total: int
    archived: int
    resolved_with_action: int


class AdminReportResolutionOutput(BaseModel):
    resolved_by: AdminReportUserOutput
    resolved_at: datetime
    action: str


class AdminReportDetailOutput(BaseModel):
    report_id: UUID
    report_number: int
    status: ReportStatusEnum
    opened_at: datetime
    target: AdminReportTargetOutput
    reason: ReportTypeEnum
    description: str
    reported_by: AdminReportUserOutput
    reported_at: datetime
    previous_reports: AdminReportPreviousReportsOutput
    resolution: AdminReportResolutionOutput | None


class AdminReportItemOutput(BaseModel):
    report_id: UUID
    report_number: int
    target_type: Literal["USER", "BUSINESS", "EVENT"] | None
    target_name: str | None
    report_count: int
    status: ReportStatusEnum
    reason: ReportTypeEnum
    description_excerpt: str
    opened_at: datetime


class AdminReportsOutput(BaseModel):
    items: list[AdminReportItemOutput]
    next_cursor: str | None
