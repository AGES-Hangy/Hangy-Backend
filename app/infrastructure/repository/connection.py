from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import UserConnection
from app.domain.enums import NotificationTypeEnum, UserConnectionStatusEnum
from app.infrastructure.repository.models import UserConnectionModel
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository


class SqlAlchemyConnectionRepository:
    def __init__(
        self, db: Session, notification_repo: SqlAlchemyNotificationRepository
    ) -> None:
        self.db = db
        self.notification_repo = notification_repo

    def get_by_id_for_update(self, connection_id: UUID) -> UserConnection | None:
        model = self.db.scalar(
            select(UserConnectionModel)
            .where(UserConnectionModel.connection_id == connection_id)
            .with_for_update()
        )
        return self._to_entity(model) if model is not None else None

    def create(self, requester_id: UUID, receiver_id: UUID) -> UserConnection:
        model = UserConnectionModel(
            requester_id=requester_id,
            receiver_id=receiver_id,
            status=UserConnectionStatusEnum.PENDING,
        )
        self.db.add(model)
        self.db.flush()
        self.notification_repo.notify_connection(
            recipient_id=receiver_id,
            connection_id=model.connection_id,
            type=NotificationTypeEnum.CONNECTION_REQUEST,
        )
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def accept(self, connection_id: UUID) -> UserConnection:
        model = self.db.scalar(
            select(UserConnectionModel).where(
                UserConnectionModel.connection_id == connection_id
            )
        )
        if model is None:
            raise ValueError("A connection validated by the service must exist")
        model.status = UserConnectionStatusEnum.CONFIRMED
        self.notification_repo.notify_connection(
            recipient_id=model.requester_id,
            connection_id=connection_id,
            type=NotificationTypeEnum.CONNECTION_ACCEPTED,
        )
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def reject(self, connection_id: UUID) -> UserConnection:
        model = self.db.scalar(
            select(UserConnectionModel).where(
                UserConnectionModel.connection_id == connection_id
            )
        )
        if model is None:
            raise ValueError("A connection validated by the service must exist")
        model.status = UserConnectionStatusEnum.REJECTED
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: UserConnectionModel) -> UserConnection:
        return UserConnection(
            connection_id=model.connection_id,
            requester_id=model.requester_id,
            receiver_id=model.receiver_id,
            status=model.status,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )
