from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import EventParticipantStatusEnum


class EventParticipantUserOutput(BaseModel):
    id: UUID
    name: str | None


class EventParticipantItemOutput(BaseModel):
    participant_id: UUID
    user: EventParticipantUserOutput
    status: EventParticipantStatusEnum
    joined_at: datetime


class EventParticipantsOutput(BaseModel):
    items: list[EventParticipantItemOutput]
    counts: dict[str, int]
    next_cursor: str | None
