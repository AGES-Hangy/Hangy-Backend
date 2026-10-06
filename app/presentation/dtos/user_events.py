from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import EventParticipantStatusEnum


class UserEventOutput(BaseModel):
    event_id: UUID
    title: str
    event_date: datetime
    location_name: str | None
    cover_photo_url: str | None
    participation_status: EventParticipantStatusEnum


class UserEventsOutput(BaseModel):
    items: list[UserEventOutput]
    next_cursor: str | None