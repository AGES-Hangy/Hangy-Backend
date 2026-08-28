from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventParticipantStatusEnum


@dataclass(frozen=True, slots=True)
class EventParticipant:
    participant_id: UUID | None
    user_id: UUID
    event_id: UUID
    status: EventParticipantStatusEnum
    joined_at: datetime
    updated_at: datetime
