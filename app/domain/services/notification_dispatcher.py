import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain.enums import NotificationTypeEnum
from app.domain.services.push import NullPushSender, PushSender

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PushContext:
    """Ids the push needs that the caller of dispatch() does not always have."""

    event_id: UUID | None = None
    sender_id: UUID | None = None


class NotificationRepository(Protocol):
    def notify_connection(
        self,
        recipient_id: UUID,
        connection_id: UUID,
        type: NotificationTypeEnum,
    ) -> UUID: ...

    def notify_participant(
        self,
        recipient_id: UUID,
        participant_id: UUID,
        type: NotificationTypeEnum,
    ) -> UUID: ...

    def notify_event_cancelled(self, recipient_id: UUID, event_id: UUID) -> UUID: ...

    def notify_event_updated(self, recipient_id: UUID, event_id: UUID) -> UUID: ...

    def get_push_context(
        self,
        type: NotificationTypeEnum,
        *,
        connection_id: UUID | None = None,
        participant_id: UUID | None = None,
        event_id: UUID | None = None,
    ) -> PushContext: ...


class DeviceTokenRepository(Protocol):
    def list_tokens_by_user(self, user_id: UUID) -> list[str]: ...

    def delete_by_tokens(self, tokens: list[str]) -> None: ...


class NullDeviceTokenRepository:
    """No-op repository used when no DeviceTokenRepository is configured."""

    def list_tokens_by_user(self, user_id: UUID) -> list[str]:
        return []

    def delete_by_tokens(self, tokens: list[str]) -> None:
        return None


PUSH_COPY: dict[NotificationTypeEnum, tuple[str, str]] = {
    NotificationTypeEnum.CONNECTION_REQUEST: (
        "Novo pedido de conexão",
        "Alguém quer se conectar com você",
    ),
    NotificationTypeEnum.CONNECTION_ACCEPTED: (
        "Pedido de conexão aceito",
        "Sua solicitação de conexão foi aceita",
    ),
    NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST: (
        "Novo pedido de participação",
        "Alguém quer participar do seu evento",
    ),
    NotificationTypeEnum.EVENT_REQUEST_APPROVED: (
        "Pedido aprovado",
        "Seu pedido de participação foi aprovado",
    ),
    NotificationTypeEnum.EVENT_REQUEST_REJECTED: (
        "Pedido recusado",
        "Seu pedido de participação foi recusado",
    ),
    NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED: (
        "Participante cancelou presença",
        "Um participante cancelou a presença no seu evento",
    ),
    NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED: (
        "Você foi removido do evento",
        "O organizador removeu você do evento",
    ),
    NotificationTypeEnum.EVENT_PARTICIPANT_JOINED: (
        "Novo participante",
        "Alguém entrou no seu evento",
    ),
    NotificationTypeEnum.EVENT_UPDATED: (
        "Evento atualizado",
        "Um evento que você participa foi atualizado",
    ),
    NotificationTypeEnum.EVENT_CANCELLED: (
        "Evento cancelado",
        "Um evento que você participa foi cancelado",
    ),
    NotificationTypeEnum.EVENT_STARTING_SOON: (
        "Evento começando",
        "Um evento que você participa começa em breve",
    ),
}


class NotificationDispatcher:
    def __init__(
        self,
        repository: NotificationRepository,
        device_repository: DeviceTokenRepository | None = None,
        push_sender: PushSender | None = None,
    ) -> None:
        self.repository = repository
        self.device_repository = device_repository or NullDeviceTokenRepository()
        self.push_sender = push_sender or NullPushSender()

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
                notification_id = self.repository.notify_connection(
                    recipient_id, connection_id, type
                )
                self._send_push(
                    recipient_id, type, notification_id, connection_id=connection_id
                )

            elif type in (
                NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
                NotificationTypeEnum.EVENT_REQUEST_APPROVED,
                NotificationTypeEnum.EVENT_REQUEST_REJECTED,
                NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
                NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED,
                NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
                NotificationTypeEnum.EVENT_STARTING_SOON,
            ):
                if participant_id is None:
                    raise ValueError(
                        "participant_id required for participant notifications"
                    )
                notification_id = self.repository.notify_participant(
                    recipient_id, participant_id, type
                )
                self._send_push(
                    recipient_id, type, notification_id, participant_id=participant_id
                )

            elif type is NotificationTypeEnum.EVENT_CANCELLED:
                if event_id is None:
                    raise ValueError(
                        "event_id required for event_cancelled notifications"
                    )
                notification_id = self.repository.notify_event_cancelled(
                    recipient_id, event_id
                )
                self._send_push(recipient_id, type, notification_id, event_id=event_id)

            elif type is NotificationTypeEnum.EVENT_UPDATED:
                if event_id is None:
                    raise ValueError(
                        "event_id required for event_updated notifications"
                    )
                notification_id = self.repository.notify_event_updated(
                    recipient_id, event_id
                )
                self._send_push(recipient_id, type, notification_id, event_id=event_id)

            else:
                logger.warning("Unhandled notification type: %s", type)

        except Exception:
            logger.exception("Notification dispatch failed for type=%s", type)

    def _send_push(
        self,
        recipient_id: UUID,
        type: NotificationTypeEnum,
        notification_id: UUID,
        *,
        connection_id: UUID | None = None,
        participant_id: UUID | None = None,
        event_id: UUID | None = None,
    ) -> None:
        tokens = self.device_repository.list_tokens_by_user(recipient_id)
        if not tokens:
            return

        context = self.repository.get_push_context(
            type,
            connection_id=connection_id,
            participant_id=participant_id,
            event_id=event_id,
        )
        event_id = event_id or context.event_id

        title, body = PUSH_COPY[type]
        data = {"type": type.value, "notification_id": str(notification_id)}
        if connection_id is not None:
            data["connection_id"] = str(connection_id)
        if participant_id is not None:
            data["participant_id"] = str(participant_id)
        if event_id is not None:
            data["event_id"] = str(event_id)
        if context.sender_id is not None:
            data["user_id"] = str(context.sender_id)

        rejected_tokens = self.push_sender.send(tokens, title, body, data)
        if rejected_tokens:
            self.device_repository.delete_by_tokens(rejected_tokens)
