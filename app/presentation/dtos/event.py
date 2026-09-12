from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class CreateInviteLinkOutput(BaseModel):
    invite_id: UUID
    token: str
    url: str
    expires_at: datetime


class CancelEventInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CancelEventOutput(BaseModel):
    event_id: UUID
    status: EventStatusEnum
    updated_at: datetime


class EventShareOutput(BaseModel):
    url: str
    web_url: str
    title: str
    event_date: datetime | None
    location_name: str | None
    cover_photo_url: str | None


class UpdateEventInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    event_date: datetime | None = None
    end_date: datetime | None = None
    location: EventLocationInput | None = None
    location_name: str | None = Field(default=None, max_length=120)
    tag_ids: list[UUID] | None = None
    cover_photo_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def provided_required_values_cannot_be_null(self) -> UpdateEventInput:
        required_values = {"title", "event_date", "end_date", "location", "tag_ids"}
        for field in self.model_fields_set & required_values:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class UpdateEventOutput(BaseModel):
    event_id: UUID
    title: str
    event_date: datetime
    status: EventStatusEnum
    updated_at: datetime
