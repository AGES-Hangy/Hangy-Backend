from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.event import Event, EventLocationView


@dataclass(frozen=True, slots=True)
class EventShare:
    """The public metadata rendered by a native share sheet."""

    url: str
    web_url: str
    title: str
    event_date: datetime | None
    # Resolved for a viewer without a session: whoever receives the link.
    location: EventLocationView
    cover_photo_url: str | None


@dataclass(frozen=True, slots=True)
class EventInvitePreview:
    """An event resolved from an invite link, before the viewer logs in."""

    event: Event
    location: EventLocationView
