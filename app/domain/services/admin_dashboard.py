__all__ = ["AdminDashboardRepository", "AdminDashboardService"]

from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.domain.entities import (
    AdminDashboard,
    DashboardRecentReport,
    DashboardReportCounts,
    DashboardUserCounts,
)
from app.domain.enums import ReportStatusEnum

RECENT_REPORTS_LIMIT = 5
# Resolved and rejected reports belong to the full queue, not to the dashboard.
RECENT_REPORTS_STATUSES = (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)
NEW_REPORTS_WINDOW = timedelta(hours=24)
NEW_USERS_WINDOW = timedelta(days=7)


class AdminDashboardRepository(Protocol):
    def get_report_counts(self, opened_since: datetime) -> DashboardReportCounts: ...

    def get_user_counts(
        self,
        now: datetime,
        created_since: datetime,
        end_of_today: datetime,
    ) -> DashboardUserCounts: ...

    def list_recent_reports(
        self, statuses: tuple[ReportStatusEnum, ...], limit: int
    ) -> list[DashboardRecentReport]: ...


class AdminDashboardService:
    def __init__(self, repository: AdminDashboardRepository) -> None:
        self.repository = repository

    def get_dashboard(self, now: datetime | None = None) -> AdminDashboard:
        now = now or datetime.now(UTC)
        # "Today" is the UTC day: the API has no per-admin timezone.
        end_of_today = datetime.combine(
            now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )
        return AdminDashboard(
            report_counts=self.repository.get_report_counts(
                opened_since=now - NEW_REPORTS_WINDOW
            ),
            user_counts=self.repository.get_user_counts(
                now=now,
                created_since=now - NEW_USERS_WINDOW,
                end_of_today=end_of_today,
            ),
            recent_reports=self.repository.list_recent_reports(
                statuses=RECENT_REPORTS_STATUSES,
                limit=RECENT_REPORTS_LIMIT,
            ),
        )
