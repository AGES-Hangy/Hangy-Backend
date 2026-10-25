from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.domain.entities import BlockedUser, UserBlock
from app.domain.enums import EventParticipantStatusEnum, UserConnectionStatusEnum
from app.domain.services.block import UserAlreadyBlockedError
from app.infrastructure.repository.block_access import (
    block_exists_between as block_exists_between,
)
from app.infrastructure.repository.block_access import (
    lock_user_pair,
)
from app.infrastructure.repository.connection import select_active_between
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)
from app.infrastructure.repository.notification import delete_pair_notifications


class SqlAlchemyBlockRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def exists_between(self, user_a: UUID, user_b: UUID) -> bool:
        from app.infrastructure.repository.block_access import is_blocked_for_write

        return is_blocked_for_write(self.db, user_a, user_b)

    def create(self, blocker_id: UUID, blocked_id: UUID) -> UserBlock:
        lock_user_pair(self.db, blocker_id, blocked_id)
        existing = self.db.get(UserBlockModel, (blocker_id, blocked_id))
        model = existing or UserBlockModel(blocker_id=blocker_id, blocked_id=blocked_id)
        if existing is None:
            self.db.add(model)
            self.db.flush()

        connection = self.db.scalar(
            select_active_between(self.db, blocker_id, blocked_id)
            .where(UserConnectionModel.status != UserConnectionStatusEnum.REJECTED)
            .with_for_update()
        )
        if connection is not None:
            connection.deleted_at = datetime.now(UTC)

        self.db.execute(
            update(EventParticipantModel)
            .where(
                EventParticipantModel.status.in_(
                    (
                        EventParticipantStatusEnum.PENDING,
                        EventParticipantStatusEnum.CONFIRMED,
                    )
                ),
                or_(
                    and_(
                        EventParticipantModel.user_id == blocker_id,
                        EventParticipantModel.event_id.in_(
                            select(EventModel.event_id).where(
                                EventModel.event_creator_id == blocked_id
                            )
                        ),
                    ),
                    and_(
                        EventParticipantModel.user_id == blocked_id,
                        EventParticipantModel.event_id.in_(
                            select(EventModel.event_id).where(
                                EventModel.event_creator_id == blocker_id
                            )
                        ),
                    ),
                ),
            )
            .values(
                status=EventParticipantStatusEnum.CANCELLED,
                updated_at=datetime.now(UTC),
            )
        )
        delete_pair_notifications(self.db, blocker_id, blocked_id)
        self.db.commit()
        if existing is not None:
            # Preserve 409 while repairing effects of blocks made before this fix.
            raise UserAlreadyBlockedError
        self.db.refresh(model)
        return self._to_entity(model)

    def list_blocked(
        self, blocker_id: UUID, limit: int, after: tuple[datetime, UUID] | None
    ) -> list[BlockedUser]:
        query = (
            select(UserBlockModel, UserModel)
            .join(UserModel, UserModel.user_id == UserBlockModel.blocked_id)
            .where(
                UserBlockModel.blocker_id == blocker_id,
                UserModel.deleted_at.is_(None),
            )
            .order_by(
                UserBlockModel.created_at.desc(), UserBlockModel.blocked_id.desc()
            )
            .limit(limit)
        )
        if after is not None:
            created_at, blocked_id = after
            query = query.where(
                or_(
                    UserBlockModel.created_at < created_at,
                    and_(
                        UserBlockModel.created_at == created_at,
                        UserBlockModel.blocked_id < blocked_id,
                    ),
                )
            )
        rows = self.db.execute(query).all()
        return [self._to_blocked_user(block, user) for block, user in rows]

    @staticmethod
    def _to_blocked_user(block: UserBlockModel, user: UserModel) -> BlockedUser:
        return BlockedUser(
            user_id=user.user_id,
            name=user.name,
            photo_url=user.profile_photo_url,
            blocked_at=block.created_at,
        )

    def delete(self, blocker_id: UUID, blocked_id: UUID) -> bool:
        lock_user_pair(self.db, blocker_id, blocked_id)
        result = self.db.execute(
            delete(UserBlockModel).where(
                UserBlockModel.blocker_id == blocker_id,
                UserBlockModel.blocked_id == blocked_id,
            )
        )
        self.db.commit()
        return result.rowcount > 0

    @staticmethod
    def _to_entity(model: UserBlockModel) -> UserBlock:
        return UserBlock(
            blocker_id=model.blocker_id,
            blocked_id=model.blocked_id,
            created_at=model.created_at,
        )
