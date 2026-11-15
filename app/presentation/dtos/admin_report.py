from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import (
    EventModerationStatusEnum,
    ModerationStatusEnum,
    ReportStatusEnum,
    ReportTypeEnum,
)

__all__ = [
    "AdminReportDetailOutput",
    "AdminReportEventOutput",
    "AdminReportItemOutput",
    "AdminReportOrganizerOutput",
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


class AdminReportEventOutput(BaseModel):
    id: UUID
    title: str
    moderation_status: EventModerationStatusEnum


class AdminReportOrganizerOutput(BaseModel):
    user_id: UUID
    name: str | None
    photo_url: str | None
    moderation_status: ModerationStatusEnum
    events_count: int
    reports_count: int


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
    # Only present when target.type is EVENT; omitted for user and business.
    organizer: AdminReportOrganizerOutput | None = None
    # The reported event (`id` for `PATCH /admin/events/{event_id}/moderation`).
    # Same rule as `organizer`: only for EVENT targets.
    event: AdminReportEventOutput | None = None


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
