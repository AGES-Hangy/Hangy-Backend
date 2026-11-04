"""AdminUserModerationService — single write path for ban/suspend/revert.

Called from both the report-detail screen and the user record screen (hence
the optional report_id on BAN/SUSPEND): see BanUserAction/SuspendUserAction/
RevertUserModerationAction in app.domain.entities.
"""

__all__ = [
    "AccountAlreadyBannedError",
    "AccountNotModeratedError",
    "AdminUserModerationService",
    "AuditRepository",
    "ModeratedUserNotFoundError",
    "ReportAlreadyResolvedError",
    "ReportNotFoundError",
    "ReportRepository",
    "UserModerationRepository",
    "derive_moderation_status",
]

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AuditEvent,
    BanUserAction,
    Report,
    RevertUserModerationAction,
    SuspendUserAction,
    User,
    UserModerationAction,
)
from app.domain.enums import (
    AuditActionEnum,
    ModerationStatusEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
)

# Reports still open for action; anything else (RESOLVED, REJECTED) is final.
_RESOLVABLE_REPORT_STATUSES = (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)


class UserModerationRepository(Protocol):
    def get_for_moderation(self, user_id: UUID) -> User | None: ...

    def set_moderation(
        self,
        user_id: UUID,
        *,
        banned_at: datetime | None,
        suspended_until: datetime | None,
    ) -> User: ...


class ReportRepository(Protocol):
    def get_by_id(self, report_id: UUID) -> Report | None: ...

    def resolve(
        self,
        report_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
        resolution_action: ReportResolutionActionEnum,
    ) -> None: ...


class AuditRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class ModeratedUserNotFoundError(Exception):
    """Raised when user_id matches no active account."""


class AccountAlreadyBannedError(Exception):
    """Raised when SUSPEND is requested for an account that is already banned."""


class AccountNotModeratedError(Exception):
    """Raised when REVERT is requested for an account that is already active."""


class ReportNotFoundError(Exception):
    """Raised when the informed report_id matches no report."""


class ReportAlreadyResolvedError(Exception):
    """Raised when the informed report_id is not PENDING or REVIEWED anymore."""


def derive_moderation_status(
    banned_at: datetime | None, suspended_until: datetime | None, now: datetime
) -> ModerationStatusEnum:
    """A ban wins over a suspension; an elapsed suspension is just ACTIVE."""
    if banned_at is not None:
        return ModerationStatusEnum.BANNED
    if suspended_until is not None and _as_utc(suspended_until) > now:
        return ModerationStatusEnum.SUSPENDED
    return ModerationStatusEnum.ACTIVE


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _is_moderated(
    banned_at: datetime | None, suspended_until: datetime | None, now: datetime
) -> bool:
    return (
        derive_moderation_status(banned_at, suspended_until, now)
        != ModerationStatusEnum.ACTIVE
    )


class AdminUserModerationService:
    def __init__(
        self,
        user_repository: UserModerationRepository,
        report_repository: ReportRepository,
        audit_repository: AuditRepository,
    ) -> None:
        self.user_repository = user_repository
        self.report_repository = report_repository
        self.audit_repository = audit_repository

    def apply_action(
        self,
        user_id: UUID,
        action: UserModerationAction,
        actor_id: UUID,
        now: datetime | None = None,
    ) -> User:
        now = now or datetime.now(UTC)
        current = self.user_repository.get_for_moderation(user_id)
        if current is None:
            raise ModeratedUserNotFoundError

        report_id = getattr(action, "report_id", None)
        if report_id is not None:
            self._check_report_resolvable(report_id)

        if isinstance(action, BanUserAction):
            updated = self.user_repository.set_moderation(
                user_id, banned_at=now, suspended_until=None
            )
            audit_action = AuditActionEnum.USER_BANNED
            resolution_action = ReportResolutionActionEnum.BANNED
        elif isinstance(action, SuspendUserAction):
            if current.banned_at is not None:
                raise AccountAlreadyBannedError
            updated = self.user_repository.set_moderation(
                user_id,
                banned_at=None,
                suspended_until=now + timedelta(days=action.duration_days),
            )
            audit_action = AuditActionEnum.USER_SUSPENDED
            resolution_action = ReportResolutionActionEnum.SUSPENDED
        else:
            assert isinstance(action, RevertUserModerationAction)
            if not _is_moderated(current.banned_at, current.suspended_until, now):
                raise AccountNotModeratedError
            updated = self.user_repository.set_moderation(
                user_id, banned_at=None, suspended_until=None
            )
            audit_action = AuditActionEnum.USER_REVERTED
            resolution_action = None

        if report_id is not None and resolution_action is not None:
            self.report_repository.resolve(
                report_id,
                resolved_by_id=actor_id,
                resolved_at=now,
                resolution_action=resolution_action,
            )

        self.audit_repository.add(
            AuditEvent(
                action=audit_action,
                actor_id=actor_id,
                target_id=user_id,
                created_at=now,
            )
        )
        return updated

    def _check_report_resolvable(self, report_id: UUID) -> None:
        report = self.report_repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError
        if report.status not in _RESOLVABLE_REPORT_STATUSES:
            raise ReportAlreadyResolvedError
