__all__ = [
    "AdminReportsRepository",
    "AdminReportsService",
    "ReportNotFoundError",
]

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AdminReportDetail,
    AdminReportDetailRecord,
    AdminReportPreviousCounts,
    AdminReportResolution,
    AdminReportTarget,
    AdminReportUserSummary,
    ReportTargetType,
)
from app.domain.enums import ModerationStatusEnum, ReportStatusEnum, UserTypeEnum


class ReportNotFoundError(Exception):
    pass


class AdminReportsRepository(Protocol):
    def get_report_detail(self, report_id: UUID) -> AdminReportDetailRecord | None: ...


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _derive_moderation_status(
    banned_at: datetime | None,
    suspended_until: datetime | None,
    now: datetime,
) -> ModerationStatusEnum:
    """A ban wins over a suspension; an elapsed suspension is just ACTIVE."""
    if banned_at is not None:
        return ModerationStatusEnum.BANNED
    if suspended_until is not None and _as_utc(suspended_until) > now:
        return ModerationStatusEnum.SUSPENDED
    return ModerationStatusEnum.ACTIVE


class AdminReportsService:
    def __init__(self, repository: AdminReportsRepository) -> None:
        self.repository = repository

    def get_report_detail(
        self, report_id: UUID, now: datetime | None = None
    ) -> AdminReportDetail:
        now = now or datetime.now(UTC)
        record = self.repository.get_report_detail(report_id)
        if record is None:
            raise ReportNotFoundError(f"Report {report_id} not found")
        return self._to_detail(record, now)

    @classmethod
    def _to_detail(
        cls, record: AdminReportDetailRecord, now: datetime
    ) -> AdminReportDetail:
        target = AdminReportTarget(
            type=cls._resolve_target_type(record),
            id=record.target_user_id,
            name=record.target_user_name,
            member_since=_as_utc(record.target_created_at).date(),
            event_count=record.target_event_count,
            moderation_status=_derive_moderation_status(
                record.target_banned_at,
                record.target_suspended_until,
                now,
            ),
        )
        previous_reports = AdminReportPreviousCounts(
            total=record.previous_archived_count + record.previous_resolved_count,
            archived=record.previous_archived_count,
            resolved_with_action=record.previous_resolved_count,
        )
        return AdminReportDetail(
            report_id=record.report_id,
            report_number=record.report_number,
            status=record.status,
            opened_at=_as_utc(record.opened_at),
            target=target,
            reason=record.reason,
            description=record.description,
            reported_by=AdminReportUserSummary(
                id=record.reported_by_id,
                name=record.reported_by_name,
            ),
            reported_at=_as_utc(record.reported_at),
            previous_reports=previous_reports,
            resolution=cls._resolve_resolution(record),
        )

    @staticmethod
    def _resolve_target_type(record: AdminReportDetailRecord) -> ReportTargetType:
        if record.reported_event_id is not None:
            return "EVENT"
        if record.target_user_type == UserTypeEnum.BUSINESS:
            return "BUSINESS"
        return "USER"

    @staticmethod
    def _resolve_resolution(
        record: AdminReportDetailRecord,
    ) -> AdminReportResolution | None:
        if record.status not in (
            ReportStatusEnum.RESOLVED,
            ReportStatusEnum.REJECTED,
        ):
            return None
        if (
            record.resolved_by_id is None
            or record.resolved_at is None
            or record.resolution_action is None
        ):
            return None
        return AdminReportResolution(
            resolved_by=AdminReportUserSummary(
                id=record.resolved_by_id,
                name=record.resolved_by_name,
            ),
            resolved_at=_as_utc(record.resolved_at),
            action=str(record.resolution_action),
        )

