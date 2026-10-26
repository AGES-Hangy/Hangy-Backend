from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.tag import Tag
from app.domain.enums import (
    ConnectionDirectionEnum,
    UserConnectionStatusEnum,
    UserTypeEnum,
)

__all__ = ["UserProfile", "UserProfileCounts", "UserProfileData"]


@dataclass(frozen=True, slots=True)
class UserProfileCounts:
    past: int
    confirmed: int
    created: int
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


@dataclass(frozen=True, slots=True)
class UserProfileData:
    user_id: UUID
    user_type: UserTypeEnum
    name: str | None
    description: str | None
    photo_url: str | None
    tags: tuple[Tag, ...]
    connection_status: UserConnectionStatusEnum | None
    is_following: bool
    connections_count: int
    connection_id: UUID | None = None
    connection_direction: ConnectionDirectionEnum | None = None
    followers_count: int | None = None
    # Created events and gallery photos, as the viewer may see them.
    events_count: int | None = None
    photos_count: int | None = None
