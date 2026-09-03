from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EventPrivacyEnum, EventStatusEnum


class EventLocationInput(BaseModel):
    """The coordinates where the event happens."""

    latitude: float
    longitude: float


class CreateEventInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=50)
    event_date: datetime
    end_date: datetime
    location: EventLocationInput
    description: str | None = Field(default=None, max_length=1000)
    location_name: str | None = Field(default=None, max_length=120)
    # Nullable on purpose: an event without a limit never blocks on capacity.
    max_participants: int | None = Field(default=None, ge=1)
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC
    tag_ids: list[UUID] = Field(
        default_factory=list,
        description="Ate 5 tags; duplicatas sao ignoradas.",
    )
    cover_photo_url: str | None = Field(default=None, max_length=2048)


class EventCreatorOutput(BaseModel):
    """The organizer, as shown next to the published event."""

    id: UUID
    name: str | None


class CreateEventOutput(BaseModel):
    event_id: UUID
    title: str
    status: EventStatusEnum
    privacy: EventPrivacyEnum
    event_date: datetime
    creator: EventCreatorOutput
