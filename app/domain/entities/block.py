from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserBlock:
    blocker_id: UUID
    blocked_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BlockedUser:
    user_id: UUID
    name: str | None
    photo_url: str | None
    blocked_at: datetime


@dataclass(frozen=True, slots=True)
class BlockedUsersPage:
    items: tuple[BlockedUser, ...]
    next_cursor: str | None
