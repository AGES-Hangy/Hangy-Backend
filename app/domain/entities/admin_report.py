from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.domain.enums import (
    ModerationStatusEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserTypeEnum,
)

__all__ = [
    "AdminReportDetail",
    "AdminReportDetailRecord",
    "AdminReportOrganizer",
    "AdminReportPreviousCounts",
    "AdminReportQueueItem",
    "AdminReportResolution",
    "AdminReportTarget",
    "AdminReportUserSummary",
    "AdminReportsPage",
    "ReportTargetType",
]

ReportTargetType = Literal["USER", "BUSINESS", "EVENT"]


@dataclass(frozen=True, slots=True)
class AdminReportUserSummary:
    id: UUID
    name: str | None


@dataclass(frozen=True, slots=True)
class AdminReportTarget:
    type: ReportTargetType
    id: UUID
    name: str | None
    member_since: date
    event_count: int
    moderation_status: ModerationStatusEnum


@dataclass(frozen=True, slots=True)
class AdminReportOrganizer:
    """The organizer behind a reported event, shaped like a user-list row."""

    user_id: UUID
    name: str | None
    photo_url: str | None
    moderation_status: ModerationStatusEnum
    events_count: int
    reports_count: int


@dataclass(frozen=True, slots=True)
class AdminReportPreviousCounts:
    total: int
    archived: int
    resolved_with_action: int


@dataclass(frozen=True, slots=True)
class AdminReportResolution:
    resolved_by: AdminReportUserSummary
    resolved_at: datetime
    action: str


@dataclass(frozen=True, slots=True)
class AdminReportDetailRecord:
    """A report and its related target/reporter/resolver data before derivation."""

    report_id: UUID
    report_number: int
    status: ReportStatusEnum
    opened_at: datetime
    reported_at: datetime
    reason: ReportTypeEnum
    description: str
    reported_event_id: UUID | None
    target_user_id: UUID
    target_user_name: str | None
    target_user_type: UserTypeEnum
    target_created_at: datetime
    target_banned_at: datetime | None
    target_suspended_until: datetime | None
    target_event_count: int
    reported_by_id: UUID
    reported_by_name: str | None
    previous_archived_count: int
    previous_resolved_count: int
    resolved_by_id: UUID | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    resolution_action: str | None = None
    # Only filled for event reports, where the target is the event's organizer.
    target_photo_url: str | None = None
    target_reports_count: int = 0


@dataclass(frozen=True, slots=True)
class AdminReportDetail:
    report_id: UUID
    report_number: int
    status: ReportStatusEnum
    opened_at: datetime
    target: AdminReportTarget
    reason: ReportTypeEnum
    description: str
    reported_by: AdminReportUserSummary
    reported_at: datetime
    previous_reports: AdminReportPreviousCounts
    resolution: AdminReportResolution | None = None
    organizer: AdminReportOrganizer | None = None


@dataclass(frozen=True, slots=True)
class AdminReportQueueItem:
    report_id: UUID
    report_number: int
    report_type: ReportTypeEnum
    status: ReportStatusEnum
    description: str
    opened_at: datetime
    report_count: int
    reported_user_name: str | None
    reported_user_type: UserTypeEnum | None
    reported_event_title: str | None


@dataclass(frozen=True, slots=True)
class AdminReportsPage:
    items: tuple[AdminReportQueueItem, ...]
    next_cursor: str | None
