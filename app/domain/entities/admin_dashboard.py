from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import ReportStatusEnum, ReportTypeEnum, UserTypeEnum


@dataclass(frozen=True, slots=True)
class DashboardReportCounts:
    open: int
    open_last_24h: int
    in_review: int
    in_review_moderators: int


@dataclass(frozen=True, slots=True)
class DashboardUserCounts:
    active: int
    active_new_this_week: int
    suspended: int
    suspended_expiring_today: int


@dataclass(frozen=True, slots=True)
class DashboardRecentReport:
    report_id: UUID
    report_type: ReportTypeEnum
    status: ReportStatusEnum
    description: str
    opened_at: datetime
    # How many (non-deleted) reports point at the same user or event.
    report_count: int
    # Only one of the two targets is set; the assembler decides which one to show.
    reported_user_name: str | None = None
    reported_user_type: UserTypeEnum | None = None
    reported_event_title: str | None = None


@dataclass(frozen=True, slots=True)
class AdminDashboard:
    report_counts: DashboardReportCounts
    user_counts: DashboardUserCounts
    recent_reports: list[DashboardRecentReport]