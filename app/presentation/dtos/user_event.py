from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import EventPrivacyEnum


class UserEventOutput(BaseModel):
    # Only what the profile card renders: nothing about the organizer leaks.
    event_id: UUID
    title: str
    event_date: datetime
    location_name: str | None
    cover_photo_url: str | None
    privacy: EventPrivacyEnum


class UserEventsOutput(BaseModel):
    items: list[UserEventOutput]
    next_cursor: str | None
