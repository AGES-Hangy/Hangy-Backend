from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserPhoto:
    """A photo a user published on an event experience."""

    photo_id: UUID
    photo_url: str
    event_id: UUID
    event_title: str
    created_at: datetime
    # The text of the experience the photo belongs to.
    description: str | None = None


@dataclass(frozen=True, slots=True)
class UserPhotosPage:
    items: tuple[UserPhoto, ...]
    next_cursor: str | None
