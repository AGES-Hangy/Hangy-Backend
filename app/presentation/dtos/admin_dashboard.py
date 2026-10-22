__all__ = ["AdminDashboardOutput", "AdminDashboardRecentReportOutput"]

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import ReportStatusEnum, ReportTypeEnum


class AdminDashboardRecentReportOutput(BaseModel):
    report_id: UUID
    target_type: Literal["USER", "BUSINESS", "EVENT"] | None
    target_name: str | None
    report_count: int
    status: ReportStatusEnum
    reason: ReportTypeEnum
    description_excerpt: str
    opened_at: datetime


class AdminDashboardOutput(BaseModel):
    reports_open: int
    reports_open_last_24h: int
    reports_in_review: int
    reports_in_review_moderators: int
    active_users: int
    active_users_new_this_week: int
    suspended_accounts: int
    suspended_accounts_expiring_today: int
    recent_reports: list[AdminDashboardRecentReportOutput]