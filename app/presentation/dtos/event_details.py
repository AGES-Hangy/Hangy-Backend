from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import (
    EventAvailableActionEnum,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserTypeEnum,
)


class EventDetailsLocationOutput(BaseModel):
    latitude: float
    longitude: float


class EventDetailsTagOutput(BaseModel):
    id: UUID
    name: str


class EventDetailsOrganizerOutput(BaseModel):
    id: UUID
    name: str | None
    user_type: UserTypeEnum


class EventDetailsParticipantOutput(BaseModel):
    participant_id: UUID
    user_id: UUID
    name: str | None
    user_type: UserTypeEnum
    avatar_url: str | None
    status: EventParticipantStatusEnum
    requested_at: datetime


class EventDetailsViewerOutput(BaseModel):
    is_organizer: bool
    participation_status: EventParticipantStatusEnum | None
    can_see_participants: bool
    available_action: EventAvailableActionEnum


class EventParticipantsPreviewOutput(BaseModel):
    count: int
    items: list[EventDetailsParticipantOutput]


class EventDetailsOutput(BaseModel):
    event_id: UUID
    title: str
    description: str | None
    event_date: datetime
    end_date: datetime
    location: EventDetailsLocationOutput
    location_name: str | None
    privacy: EventPrivacyEnum
    status: EventStatusEnum
    cover_photo_url: str | None
    tags: list[EventDetailsTagOutput]
    organizer: EventDetailsOrganizerOutput
    viewer: EventDetailsViewerOutput
    participants_preview: EventParticipantsPreviewOutput | None
