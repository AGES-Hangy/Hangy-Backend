"""AdminEventModerationService — write path for admin actions on an event.

Only REMOVE exists today. It is a moderation soft delete: the event leaves every
listing and detail, its active participations are cancelled and everybody
involved is notified, while the organizer's account is left alone (ban/suspend
stay on the user moderation flow).
"""

__all__ = [
    "AdminEventModerationService",
    "EventAlreadyRemovedError",
    "EventModerationNotFoundError",
    "EventModerationReportRepository",
    "EventModerationRepository",
    "ReportNotAboutEventError",
]

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    EventForModeration,
    EventModerationAction,
    EventModerationResult,
    RemoveEventAction,
    Report,
)
from app.domain.enums import (
    AuditActionEnum,
    AuditTargetTypeEnum,
    EventModerationStatusEnum,
    NotificationTypeEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
)
from app.domain.services.admin_reports import ReportNotFoundError
from app.domain.services.admin_user_moderation import ReportAlreadyResolvedError
from app.domain.services.audit_logger import AuditLogger
from app.domain.services.notification_dispatcher import NotificationDispatcher

# Reports still open for action; anything else (RESOLVED, REJECTED) is final.
_RESOLVABLE_REPORT_STATUSES = (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)


class EventModerationRepository(Protocol):
    def get_for_moderation(self, event_id: UUID) -> EventForModeration | None: ...

    def remove(self, event_id: UUID, removed_at: datetime) -> None: ...

    def cancel_active_participations(self, event_id: UUID) -> list[UUID]: ...

    def commit(self) -> None: ...


class EventModerationReportRepository(Protocol):
    def get_by_id(self, report_id: UUID) -> Report | None: ...

    def resolve_open_for_event(
        self,
        event_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
        resolution_action: ReportResolutionActionEnum,
    ) -> int: ...


class EventModerationNotFoundError(Exception):
    """Raised when event_id matches no event."""


class EventAlreadyRemovedError(Exception):
    """Raised when the event was already removed by moderation."""


class ReportNotAboutEventError(Exception):
    """Raised when the informed report_id does not report this event."""


class AdminEventModerationService:
    def __init__(
        self,
        event_repository: EventModerationRepository,
        report_repository: EventModerationReportRepository,
        audit_logger: AuditLogger,
        dispatcher: NotificationDispatcher,
    ) -> None:
        self.event_repository = event_repository
        self.report_repository = report_repository
        self.audit_logger = audit_logger
        self.dispatcher = dispatcher

    def apply_action(
        self,
        event_id: UUID,
        action: EventModerationAction,
        actor_id: UUID,
        now: datetime | None = None,
    ) -> EventModerationResult:
        assert isinstance(action, RemoveEventAction)
        now = now or datetime.now(UTC)

        event = self.event_repository.get_for_moderation(event_id)
        if event is None:
            raise EventModerationNotFoundError
        if event.moderation_status is EventModerationStatusEnum.REMOVED:
            raise EventAlreadyRemovedError
        if event.deleted_at is not None:
            # Gone for another reason (e.g. the organizer's account deletion).
            raise EventModerationNotFoundError

        if action.report_id is not None:
            self._check_report_resolvable(action.report_id, event_id)

        self.event_repository.remove(event_id, now)
        participant_ids = self.event_repository.cancel_active_participations(event_id)
        # Same transaction: reports open on this event are settled by this
        # removal, whether or not the admin came from one of them.
        self.report_repository.resolve_open_for_event(
            event_id,
            resolved_by_id=actor_id,
            resolved_at=now,
            resolution_action=ReportResolutionActionEnum.EVENT_REMOVED,
        )

        # The organizer is told too. dict.fromkeys drops a duplicate when the
        # organizer also has a participation row, keeping the order.
        for recipient_id in dict.fromkeys([event.event_creator_id, *participant_ids]):
            self.dispatcher.dispatch(
                NotificationTypeEnum.EVENT_REMOVED,
                recipient_id=recipient_id,
                event_id=event_id,
            )

        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.EVENT_REMOVED,
            target_type=AuditTargetTypeEnum.EVENT,
            target_id=event_id,
        )
        # The audit write is a savepoint (see AuditLogger): it never fails this
        # commit even when it was itself rolled back.
        self.event_repository.commit()
        return EventModerationResult(
            event_id=event_id,
            moderation_status=EventModerationStatusEnum.REMOVED,
            removed_at=now,
            report_id=action.report_id,
            report_status=(
                ReportStatusEnum.RESOLVED if action.report_id is not None else None
            ),
        )

    def _check_report_resolvable(self, report_id: UUID, event_id: UUID) -> None:
        report = self.report_repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError
        if report.reported_event_id != event_id:
            raise ReportNotAboutEventError
        if report.status not in _RESOLVABLE_REPORT_STATUSES:
            raise ReportAlreadyResolvedError
