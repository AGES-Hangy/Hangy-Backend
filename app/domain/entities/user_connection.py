from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import UserConnectionStatusEnum


@dataclass(frozen=True, slots=True)
class UserConnection:
    connection_id: UUID | None
    requester_id: UUID
    receiver_id: UUID
    status: UserConnectionStatusEnum
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserFollow:
    follower_id: UUID
    followed_business_id: UUID
    created_at: datetime
