from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import DevicePlatformEnum


class RegisterDeviceInput(BaseModel):
    device_token: str
    platform: DevicePlatformEnum


class RegisterDeviceOutput(BaseModel):
    device_id: UUID
    platform: DevicePlatformEnum
    created_at: datetime
