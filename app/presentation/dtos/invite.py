from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import EventParticipantStatusEnum


class AcceptInviteOutput(BaseModel):
    participant_id: UUID
    event_id: UUID
    status: EventParticipantStatusEnum
    updated_at: datetime
