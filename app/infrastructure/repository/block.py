from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.entities import UserBlock
from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository.models import UserBlockModel, UserConnectionModel


class SqlAlchemyBlockRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def exists_between(self, user_a: UUID, user_b: UUID) -> bool:
        return (
            self.db.scalar(
                select(UserBlockModel).where(
                    or_(
                        (UserBlockModel.blocker_id == user_a)
                        & (UserBlockModel.blocked_id == user_b),
                        (UserBlockModel.blocker_id == user_b)
                        & (UserBlockModel.blocked_id == user_a),
                    )
                )
            )
            is not None
        )

    def create(self, blocker_id: UUID, blocked_id: UUID) -> UserBlock:
        model = UserBlockModel(blocker_id=blocker_id, blocked_id=blocked_id)
        self.db.add(model)

        connection = self.db.scalar(
            select(UserConnectionModel)
            .where(
                UserConnectionModel.deleted_at.is_(None),
                UserConnectionModel.status != UserConnectionStatusEnum.REJECTED,
                or_(
                    (UserConnectionModel.requester_id == blocker_id)
                    & (UserConnectionModel.receiver_id == blocked_id),
                    (UserConnectionModel.requester_id == blocked_id)
                    & (UserConnectionModel.receiver_id == blocker_id),
                ),
            )
            .with_for_update()
        )
        if connection is not None:
            connection.deleted_at = datetime.now(UTC)

        self.db.flush()
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: UserBlockModel) -> UserBlock:
        return UserBlock(
            blocker_id=model.blocker_id,
            blocked_id=model.blocked_id,
            created_at=model.created_at,
        )
