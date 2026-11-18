"""AdminReportArchiveService — write paths that only touch the report itself.

The sibling of AdminUserModerationService's BAN/SUSPEND and
AdminEventModerationService's REMOVE. Here the reported account or event is
never touched:

- archive: the investigation concluded the report does not proceed (REJECTED);
- review: an admin took the report, PENDING -> REVIEWED ("Em análise");
- resolve without action: the report was handled and closes as RESOLVED with
  resolution_action=NO_ACTION.
"""

__all__ = [
    "AdminReportArchiveService",
    "ReportNotPendingError",
    "ReportArchiveRepository",
]

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Report
from app.domain.enums import (
    AuditActionEnum,
    AuditTargetTypeEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
)
from app.domain.services.admin_reports import ReportNotFoundError
from app.domain.services.admin_user_moderation import ReportAlreadyResolvedError
from app.domain.services.audit_logger import AuditLogger

# Reports still open for action; anything else (RESOLVED, REJECTED) is final.
_RESOLVABLE_REPORT_STATUSES = (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)


class ReportNotPendingError(Exception):
    """Raised when a report taken for review is already REVIEWED."""


class ReportArchiveRepository(Protocol):
    def get_by_id(
        self, report_id: UUID, *, for_update: bool = False
    ) -> Report | None: ...

    def archive(
        self,
        report_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
    ) -> None: ...

    def mark_reviewed(self, report_id: UUID) -> None: ...

    def resolve(
        self,
        report_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
        resolution_action: ReportResolutionActionEnum,
    ) -> None: ...

    def commit(self) -> None: ...


class AdminReportArchiveService:
    def __init__(
        self,
        report_repository: ReportArchiveRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self.report_repository = report_repository
        self.audit_logger = audit_logger

    def archive_report(
        self,
        report_id: UUID,
        actor_id: UUID,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        report = self.report_repository.get_by_id(report_id, for_update=True)
        if report is None:
            raise ReportNotFoundError
        if report.status not in _RESOLVABLE_REPORT_STATUSES:
            raise ReportAlreadyResolvedError

        self.report_repository.archive(
            report_id,
            resolved_by_id=actor_id,
            resolved_at=now,
        )
        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.REPORT_ARCHIVED,
            target_type=AuditTargetTypeEnum.REPORT,
            target_id=report_id,
        )
        # The audit write is a savepoint (see AuditLogger): it never fails this
        # commit even when it was itself rolled back.
        self.report_repository.commit()

    def review_report(self, report_id: UUID, actor_id: UUID) -> None:
        """PENDING -> REVIEWED. The report stays open for any action."""
        report = self.report_repository.get_by_id(report_id, for_update=True)
        if report is None:
            raise ReportNotFoundError
        if report.status not in _RESOLVABLE_REPORT_STATUSES:
            raise ReportAlreadyResolvedError
        if report.status is not ReportStatusEnum.PENDING:
            raise ReportNotPendingError

        self.report_repository.mark_reviewed(report_id)
        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.REPORT_REVIEWED,
            target_type=AuditTargetTypeEnum.REPORT,
            target_id=report_id,
        )
        self.report_repository.commit()

    def resolve_without_action(
        self,
        report_id: UUID,
        actor_id: UUID,
        now: datetime | None = None,
    ) -> None:
        """Close an open report as RESOLVED, with nothing applied to the target."""
        now = now or datetime.now(UTC)
        report = self.report_repository.get_by_id(report_id, for_update=True)
        if report is None:
            raise ReportNotFoundError
        if report.status not in _RESOLVABLE_REPORT_STATUSES:
            raise ReportAlreadyResolvedError

        self.report_repository.resolve(
            report_id,
            resolved_by_id=actor_id,
            resolved_at=now,
            resolution_action=ReportResolutionActionEnum.NO_ACTION,
        )
        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.REPORT_RESOLVED,
            target_type=AuditTargetTypeEnum.REPORT,
            target_id=report_id,
        )
        self.report_repository.commit()
