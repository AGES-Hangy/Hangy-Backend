from uuid import UUID

from app.domain.entities import NewUserDevice
from app.presentation.dtos import RegisterDeviceInput


class DeviceMapper:
    @staticmethod
    def to_entity(dto: RegisterDeviceInput, user_id: UUID) -> NewUserDevice:
        return NewUserDevice(
            user_id=user_id,
            device_token=dto.device_token,
            platform=dto.platform,
        )
