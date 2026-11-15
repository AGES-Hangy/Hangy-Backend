"""AdminReportArchiveService — write path for archiving a report.

The sibling of AdminUserModerationService's BAN/SUSPEND and
AdminEventModerationService's REMOVE: here the investigation concluded the
report does not proceed, so only the report itself closes — the reported
account or event is never touched.
"""

__all__ = [
    "AdminReportArchiveService",
    "ReportArchiveRepository",
]

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Report
from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum, ReportStatusEnum
from app.domain.services.admin_reports import ReportNotFoundError
from app.domain.services.admin_user_moderation import ReportAlreadyResolvedError
from app.domain.services.audit_logger import AuditLogger

# Reports still open for action; anything else (RESOLVED, REJECTED) is final.
_RESOLVABLE_REPORT_STATUSES = (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)


class ReportArchiveRepository(Protocol):
    def get_by_id(self, report_id: UUID) -> Report | None: ...

    def archive(
        self,
        report_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
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
        report = self.report_repository.get_by_id(report_id)
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
