from app.domain.entities import UserDevice
from app.presentation.dtos import RegisterDeviceOutput


class DeviceAssembler:
    @staticmethod
    def to_dto(device: UserDevice) -> RegisterDeviceOutput:
        if device.device_id is None:
            raise ValueError("A persisted device must have an id")
        return RegisterDeviceOutput(
            device_id=device.device_id,
            platform=device.platform,
            created_at=device.created_at,
        )
