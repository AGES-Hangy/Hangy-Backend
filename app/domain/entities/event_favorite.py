from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventFavorite:
    """An event a personal account marked as an interest."""

    user_id: UUID
    event_id: UUID
    created_at: datetime | None = None
