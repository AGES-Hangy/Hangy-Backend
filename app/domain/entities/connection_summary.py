from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConnectionSummary:
    """The other party in a confirmed connection, as listed in /users/me/connections."""

    user_id: UUID
    name: str | None
    photo_url: str | None
    city: str | None
    connected_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectionsPage:
    items: tuple[ConnectionSummary, ...]
    next_cursor: str | None
