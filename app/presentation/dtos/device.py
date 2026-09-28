from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import DevicePlatformEnum


class RegisterDeviceInput(BaseModel):
    device_token: str = Field(min_length=20, max_length=512)
    platform: DevicePlatformEnum


class RegisterDeviceOutput(BaseModel):
    device_id: UUID
    platform: DevicePlatformEnum
    created_at: datetime
