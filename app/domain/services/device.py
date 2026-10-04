import re
from typing import Protocol
from uuid import UUID

from app.domain.entities import NewUserDevice, UserDevice

EXPO_TOKEN_PATTERN = re.compile(r"^ExponentPushToken\[.+\]$")


class DeviceRepository(Protocol):
    def upsert(self, device: NewUserDevice) -> UserDevice: ...

    def delete_by_user_and_token(self, user_id: UUID, device_token: str) -> bool: ...


class InvalidDeviceTokenError(Exception):
    """Raised when the device_token format is not a valid Expo Push Token."""


class DeviceNotFoundError(Exception):
    """Raised when no device matches the given user and token."""


class DeviceService:
    def __init__(self, repository: DeviceRepository) -> None:
        self.repository = repository

    def register(self, device: NewUserDevice) -> UserDevice:
        if not EXPO_TOKEN_PATTERN.match(device.device_token):
            raise InvalidDeviceTokenError
        return self.repository.upsert(device)

    def remove_token(self, user_id: UUID, device_token: str) -> None:
        deleted = self.repository.delete_by_user_and_token(user_id, device_token)
        if not deleted:
            raise DeviceNotFoundError
