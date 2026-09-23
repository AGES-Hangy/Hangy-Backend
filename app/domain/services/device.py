from typing import Protocol
from uuid import UUID


class DeviceNotFoundError(Exception):
    pass


class DeviceRepository(Protocol):
    def delete(self, device_token: str, user_id: UUID) -> bool:
        """Deletes the device. Returns True if deleted, False if not found."""
        ...


class DeviceService:
    def __init__(self, repository: DeviceRepository) -> None:
        self.repository = repository

    def remove_device(self, device_token: str, user_id: UUID) -> None:
        deleted = self.repository.delete(device_token, user_id)
        if not deleted:
            raise DeviceNotFoundError("Device not found")


__all__ = ["DeviceNotFoundError", "DeviceRepository", "DeviceService"]
