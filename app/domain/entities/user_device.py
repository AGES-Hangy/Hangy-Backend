from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import DevicePlatformEnum


@dataclass(frozen=True, slots=True)
class NewUserDevice:
    user_id: UUID
    device_token: str
    platform: DevicePlatformEnum


@dataclass(frozen=True, slots=True)
class UserDevice:
    device_id: UUID | None
    user_id: UUID
    device_token: str
    platform: DevicePlatformEnum
    created_at: datetime
