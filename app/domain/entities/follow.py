from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

__all__ = ["FollowedBusiness", "FollowedBusinessesPage", "UserFollow"]


@dataclass(frozen=True, slots=True)
class UserFollow:
    follower_id: UUID
    followed_business_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FollowedBusiness:
    """A business as listed in the follower's ``/users/me/following``."""

    user_id: UUID
    business_name: str | None
    followed_at: datetime
    photo_url: str | None = None
    # ``business_profile`` has no city column yet (only ``address``).
    city: str | None = None


@dataclass(frozen=True, slots=True)
class FollowedBusinessesPage:
    items: tuple[FollowedBusiness, ...]
    next_cursor: str | None
