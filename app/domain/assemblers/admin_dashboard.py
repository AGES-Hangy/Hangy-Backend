__all__ = ["AdminDashboardAssembler"]

from app.domain.entities import AdminDashboard, DashboardRecentReport
from app.domain.enums import UserTypeEnum
from app.presentation.dtos.admin_dashboard import (
    AdminDashboardOutput,
    AdminDashboardRecentReportOutput,
)

DESCRIPTION_EXCERPT_MAX_LENGTH = 80


class AdminDashboardAssembler:
    @staticmethod
    def to_dto(dashboard: AdminDashboard) -> AdminDashboardOutput:
        reports = dashboard.report_counts
        users = dashboard.user_counts
        return AdminDashboardOutput(
            reports_open=reports.open,
            reports_open_last_24h=reports.open_last_24h,
            reports_in_review=reports.in_review,
            reports_in_review_moderators=reports.in_review_moderators,
            active_users=users.active,
            active_users_new_this_week=users.active_new_this_week,
            suspended_accounts=users.suspended,
            suspended_accounts_expiring_today=users.suspended_expiring_today,
            recent_reports=[
                AdminDashboardAssembler.to_recent_report_dto(report)
                for report in dashboard.recent_reports
            ],
        )

    @staticmethod
    def to_recent_report_dto(
        report: DashboardRecentReport,
    ) -> AdminDashboardRecentReportOutput:
        target_type, target_name = AdminDashboardAssembler._resolve_target(report)
        return AdminDashboardRecentReportOutput(
            report_id=report.report_id,
            target_type=target_type,
            target_name=target_name,
            report_count=report.report_count,
            status=report.status,
            reason=report.report_type,
            description_excerpt=AdminDashboardAssembler._excerpt(report.description),
            opened_at=report.opened_at,
        )

    @staticmethod
    def _resolve_target(
        report: DashboardRecentReport,
    ) -> tuple[str | None, str | None]:
        """Pick the name the admin sees: event title, business or user name."""
        if report.reported_event_title is not None:
            return "EVENT", report.reported_event_title
        if report.reported_user_type == UserTypeEnum.BUSINESS:
            return "BUSINESS", report.reported_user_name
        if report.reported_user_type == UserTypeEnum.PERSONAL:
            return "USER", report.reported_user_name
        return None, None

    @staticmethod
    def _excerpt(description: str) -> str:
        text = description.strip()
        if len(text) <= DESCRIPTION_EXCERPT_MAX_LENGTH:
            return text
        return text[:DESCRIPTION_EXCERPT_MAX_LENGTH].rstrip() + "..."
