from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import NewUserDevice, UserDevice
from app.infrastructure.repository.models import UserDeviceModel


class SqlAlchemyUserDeviceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, device: NewUserDevice) -> UserDevice:
        model = self.db.scalar(
            select(UserDeviceModel).where(
                UserDeviceModel.device_token == device.device_token
            )
        )
        if model is not None:
            model.user_id = device.user_id
            model.platform = device.platform
        else:
            model = UserDeviceModel(
                user_id=device.user_id,
                device_token=device.device_token,
                platform=device.platform,
            )
            self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def delete_by_user_and_token(self, user_id: UUID, device_token: str) -> None:
        model = self.db.scalar(
            select(UserDeviceModel).where(
                UserDeviceModel.user_id == user_id,
                UserDeviceModel.device_token == device_token,
            )
        )
        if model is not None:
            self.db.delete(model)
            self.db.commit()

    @staticmethod
    def _to_entity(model: UserDeviceModel) -> UserDevice:
        return UserDevice(
            device_id=model.device_id,
            user_id=model.user_id,
            device_token=model.device_token,
            platform=model.platform,
            created_at=model.created_at,
        )
