import logging
from typing import Protocol
from uuid import UUID

from app.domain.enums import NotificationTypeEnum

logger = logging.getLogger(__name__)


class NotificationRepository(Protocol):
    def notify_connection(
        self,
        recipient_id: UUID,
        connection_id: UUID,
        type: NotificationTypeEnum,
    ) -> None: ...

    def notify_participant(
        self,
        recipient_id: UUID,
        participant_id: UUID,
        type: NotificationTypeEnum,
    ) -> None: ...

    def notify_event_cancelled(self, recipient_id: UUID, event_id: UUID) -> None: ...

    def notify_event_updated(self, recipient_id: UUID, event_id: UUID) -> None: ...


class NotificationDispatcher:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

    def dispatch(
        self,
        type: NotificationTypeEnum,
        *,
        recipient_id: UUID,
        actor_id: UUID | None = None,
        connection_id: UUID | None = None,
        participant_id: UUID | None = None,
        event_id: UUID | None = None,
    ) -> None:
        if actor_id is not None and actor_id == recipient_id:
            return

        try:
            if type in (
                NotificationTypeEnum.CONNECTION_REQUEST,
                NotificationTypeEnum.CONNECTION_ACCEPTED,
            ):
                if connection_id is None:
                    raise ValueError(
                        "connection_id required for connection notifications"
                    )
                self.repository.notify_connection(recipient_id, connection_id, type)

            elif type in (
                NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
                NotificationTypeEnum.EVENT_REQUEST_APPROVED,
                NotificationTypeEnum.EVENT_REQUEST_REJECTED,
                NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
                NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED,
                NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
            ):
                if participant_id is None:
                    raise ValueError(
                        "participant_id required for participant notifications"
                    )
                self.repository.notify_participant(recipient_id, participant_id, type)

            elif type is NotificationTypeEnum.EVENT_CANCELLED:
                if event_id is None:
                    raise ValueError(
                        "event_id required for event_cancelled notifications"
                    )
                self.repository.notify_event_cancelled(recipient_id, event_id)

            elif type is NotificationTypeEnum.EVENT_UPDATED:
                if event_id is None:
                    raise ValueError(
                        "event_id required for event_updated notifications"
                    )
                self.repository.notify_event_updated(recipient_id, event_id)

            else:
                logger.warning("Unhandled notification type: %s", type)

        except Exception:
            logger.exception("Notification dispatch failed for type=%s", type)
