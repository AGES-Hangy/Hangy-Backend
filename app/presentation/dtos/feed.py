from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import EventPrivacyEnum
from app.domain.services import DEFAULT_FEED_LIMIT


class FeedQuery(BaseModel):
    """Query parameters accepted by the Home feed endpoint."""

    limit: int = Field(
        default=DEFAULT_FEED_LIMIT,
        description="Maximum number of events returned per section.",
    )


class FeedTagOutput(BaseModel):
    id: UUID
    name: str


class FeedItemOutput(BaseModel):
    event_id: UUID
    title: str
    event_date: datetime | None
    location_name: str | None
    cover_photo_url: str | None
    privacy: EventPrivacyEnum
    participants_count: int


class FeedSectionOutput(BaseModel):
    tag: FeedTagOutput
    items: list[FeedItemOutput]
    has_more: bool


class FeedOutput(BaseModel):
    sections: list[FeedSectionOutput]
