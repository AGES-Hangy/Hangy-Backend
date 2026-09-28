from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import NotificationTypeEnum


@dataclass(frozen=True, slots=True)
class Notification:
    notification_id: UUID | None
    user_id: UUID
    type: NotificationTypeEnum
    created_at: datetime
    read: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectionNotification:
    notification_id: UUID
    connection_id: UUID


@dataclass(frozen=True, slots=True)
class EventParticipantNotification:
    notification_id: UUID
    participant_id: UUID


@dataclass(frozen=True, slots=True)
class EventCancelledNotification:
    notification_id: UUID
    event_id: UUID


@dataclass(frozen=True, slots=True)
class UnreadNotificationCount:
    count: int
