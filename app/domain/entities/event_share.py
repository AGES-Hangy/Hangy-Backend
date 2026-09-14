from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EventShare:
    """The public metadata rendered by a native share sheet."""

    url: str
    web_url: str
    title: str
    event_date: datetime | None
    location_name: str | None
    cover_photo_url: str | None
