from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.entities.device import Device
from app.infrastructure.repository.models.device_model import DeviceModel


class SqlAlchemyDeviceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def delete(self, device_token: str, user_id: UUID) -> bool:
        device = (
            self.db.query(DeviceModel)
            .filter(
                DeviceModel.device_token == device_token,
                DeviceModel.user_id == user_id,
            )
            .first()
        )
        if not device:
            return False

        self.db.delete(device)
        self.db.commit()
        return True

    @staticmethod
    def _to_entity(model: DeviceModel) -> Device:
        return Device(
            device_token=model.device_token,
            user_id=model.user_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


__all__ = ["SqlAlchemyDeviceRepository"]
