from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AdminReportDetail,
    AdminReportDetailRecord,
    AdminReportEvent,
    AdminReportOrganizer,
    AdminReportPreviousCounts,
    AdminReportQueueItem,
    AdminReportResolution,
    AdminReportsPage,
    AdminReportTarget,
    AdminReportUserSummary,
    ReportTargetType,
)
from app.domain.enums import ReportStatusEnum, UserTypeEnum
from app.domain.services.admin_users import derive_moderation_status
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

__all__ = [
    "DEFAULT_ADMIN_REPORTS_LIMIT",
    "MAX_ADMIN_REPORTS_LIMIT",
    "MAX_ADMIN_REPORTS_SEARCH_LENGTH",
    "MIN_ADMIN_REPORTS_LIMIT",
    "AdminReportsRepository",
    "AdminReportsService",
    "OnlyOneTargetFilterError",
    "ReportNotFoundError",
]


DEFAULT_ADMIN_REPORTS_LIMIT = 20
MIN_ADMIN_REPORTS_LIMIT = 1
MAX_ADMIN_REPORTS_LIMIT = 100
MAX_ADMIN_REPORTS_SEARCH_LENGTH = 100
MAX_REPORT_NUMBER_DIGITS = 9
# Archived (REJECTED) reports stay out of the queue unless asked for.
DEFAULT_QUEUE_STATUSES = (
    ReportStatusEnum.PENDING,
    ReportStatusEnum.REVIEWED,
    ReportStatusEnum.RESOLVED,
)


class ReportNotFoundError(Exception):
    pass


class OnlyOneTargetFilterError(Exception):
    """Raised when target_user_id and target_event_id are both informed."""


class AdminReportsRepository(Protocol):
    def get_report_detail(self, report_id: UUID) -> AdminReportDetailRecord | None: ...

    def list_queue(
        self,
        statuses: tuple[ReportStatusEnum, ...],
        search: str | None,
        report_number: int | None,
        target_user_id: UUID | None,
        target_event_id: UUID | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[AdminReportQueueItem]: ...


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AdminReportsService:
    def __init__(self, repository: AdminReportsRepository) -> None:
        self.repository = repository

    def list_reports(
        self,
        status: ReportStatusEnum | None = None,
        search: str | None = None,
        limit: int = DEFAULT_ADMIN_REPORTS_LIMIT,
        cursor: str | None = None,
        target_user_id: UUID | None = None,
        target_event_id: UUID | None = None,
    ) -> AdminReportsPage:
        if target_user_id is not None and target_event_id is not None:
            raise OnlyOneTargetFilterError
        if not MIN_ADMIN_REPORTS_LIMIT <= limit <= MAX_ADMIN_REPORTS_LIMIT:
            raise InvalidPaginationError("Limit out of bounds")
        after = decode_cursor(cursor) if cursor else None
        term, report_number = self._parse_search(search)
        statuses = DEFAULT_QUEUE_STATUSES if status is None else (status,)

        rows = self.repository.list_queue(
            statuses=statuses,
            search=term,
            report_number=report_number,
            target_user_id=target_user_id,
            target_event_id=target_event_id,
            limit=limit + 1,
            after=after,
        )
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.opened_at, last.report_id)
        return AdminReportsPage(items=tuple(rows), next_cursor=next_cursor)

    @staticmethod
    def _parse_search(search: str | None) -> tuple[str | None, int | None]:
        term = (search or "").strip()
        if not term:
            return None, None
        digits = term.removeprefix("#")
        is_number = (
            digits.isascii()
            and digits.isdigit()
            and len(digits) <= MAX_REPORT_NUMBER_DIGITS
        )
        return term, int(digits) if is_number else None

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
        target_type = cls._resolve_target_type(record)
        target = AdminReportTarget(
            type=target_type,
            id=record.target_user_id,
            name=record.target_user_name,
            member_since=_as_utc(record.target_created_at).date(),
            event_count=record.target_event_count,
            moderation_status=derive_moderation_status(
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
            organizer=(
                AdminReportOrganizer(
                    user_id=target.id,
                    name=target.name,
                    photo_url=record.target_photo_url,
                    moderation_status=target.moderation_status,
                    events_count=target.event_count,
                    reports_count=record.target_reports_count,
                )
                if target_type == "EVENT"
                else None
            ),
            event=cls._resolve_event(record),
        )

    @staticmethod
    def _resolve_event(record: AdminReportDetailRecord) -> AdminReportEvent | None:
        if (
            record.reported_event_id is None
            or record.reported_event_title is None
            or record.reported_event_moderation_status is None
        ):
            return None
        return AdminReportEvent(
            id=record.reported_event_id,
            title=record.reported_event_title,
            moderation_status=record.reported_event_moderation_status,
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
