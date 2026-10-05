from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.tag import Tag

__all__ = ["UserProfile", "UserProfileCounts"]


@dataclass(frozen=True, slots=True)
class UserProfileCounts:
    past: int
    confirmed: int
    photos: int
    connections: int


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: UUID
    name: str | None
    description: str | None
    photo_url: str | None
    tags: tuple[Tag, ...]
    counts: UserProfileCounts
