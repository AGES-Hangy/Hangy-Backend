from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class NewEventInviteLink:
    """An invite link as requested by the organizer, before it is persisted."""

    event_id: UUID
    token: str
    created_by: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EventInviteLink:
    invite_id: UUID | None
    event_id: UUID
    token: str
    created_by: UUID
    created_at: datetime
    expires_at: datetime
