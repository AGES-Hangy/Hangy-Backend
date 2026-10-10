from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import EventParticipantStatusEnum, EventPrivacyEnum


class UserEventOutput(BaseModel):
    # Only what the profile card renders: nothing about the organizer leaks.
    event_id: UUID
    title: str
    event_date: datetime
    location_name: str | None
    cover_photo_url: str | None
    privacy: EventPrivacyEnum
    participation_status: EventParticipantStatusEnum | None


class UserEventsOutput(BaseModel):
    items: list[UserEventOutput]
    next_cursor: str | None


class UserEventsTabsOutput(BaseModel):
    # Always the four keys: null is "not shown to this viewer", which is not
    # the same as a shown tab that happens to be empty.
    history: UserEventsOutput | None
    created: UserEventsOutput | None
    interests: UserEventsOutput | None
    confirmed: UserEventsOutput | None
