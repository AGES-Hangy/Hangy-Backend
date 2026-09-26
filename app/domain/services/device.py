import re
from typing import Protocol

from app.domain.entities import NewUserDevice, UserDevice

EXPO_TOKEN_PATTERN = re.compile(r"^ExponentPushToken\[.+\]$")


class DeviceRepository(Protocol):
    def upsert(self, device: NewUserDevice) -> UserDevice: ...

    def delete_by_user_and_token(self, user_id, device_token: str) -> None: ...


class InvalidDeviceTokenError(Exception):
    """Raised when the device_token format is not a valid Expo Push Token."""


class DeviceService:
    def __init__(self, repository: DeviceRepository) -> None:
        self.repository = repository

    def register(self, device: NewUserDevice) -> UserDevice:
        if not EXPO_TOKEN_PATTERN.match(device.device_token):
            raise InvalidDeviceTokenError
        return self.repository.upsert(device)

    def remove_token(self, user_id, device_token: str) -> None:
        self.repository.delete_by_user_and_token(user_id, device_token)
