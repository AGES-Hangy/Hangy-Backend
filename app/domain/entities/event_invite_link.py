from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventInviteLink:
    invite_id: UUID | None
    event_id: UUID
    token: str
    created_at: datetime
    expires_at: datetime
