from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

__all__ = ["UserFollow"]


@dataclass(frozen=True, slots=True)
class UserFollow:
    follower_id: UUID
    followed_business_id: UUID
    created_at: datetime
