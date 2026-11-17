from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import (
    EventModerationStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    ModerationStatusEnum,
)

__all__ = [
    "AdminEventDetailOutput",
    "AdminEventMetricsOutput",
    "AdminEventOrganizerOutput",
]


class AdminEventOrganizerOutput(BaseModel):
    user_id: UUID
    name: str | None
    photo_url: str | None
    moderation_status: ModerationStatusEnum
    event_count: int
    report_count: int


class AdminEventMetricsOutput(BaseModel):
    participant_count: int
    pending_count: int
    report_count: int
    report_upheld_count: int


class AdminEventDetailOutput(BaseModel):
    event_id: UUID
    title: str
    description: str | None
    event_date: datetime
    end_date: datetime
    location_name: str | None
    location_neighborhood: str | None
    location_city: str | None
    latitude: float
    longitude: float
    privacy: EventPrivacyEnum
    status: EventStatusEnum
    moderation_status: EventModerationStatusEnum
    removed_at: datetime | None
    cover_photo_url: str | None
    max_participants: int | None
    created_at: datetime
    tags: list[str]
    organizer: AdminEventOrganizerOutput
    metrics: AdminEventMetricsOutput
