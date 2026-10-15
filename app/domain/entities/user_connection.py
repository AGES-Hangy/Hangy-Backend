from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import UserConnectionStatusEnum


@dataclass(frozen=True, slots=True)
class UserConnection:
    connection_id: UUID | None
    requester_id: UUID
    receiver_id: UUID
    status: UserConnectionStatusEnum
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PendingConnection:
    """A connection request the user received and has not answered yet."""

    connection_id: UUID
    requester_id: UUID
    requester_name: str | None
    requester_photo_url: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PendingConnectionsPage:
    items: tuple[PendingConnection, ...]
    next_cursor: str | None
