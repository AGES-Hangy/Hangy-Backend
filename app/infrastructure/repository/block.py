from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import BlockedUser, UserBlock
from app.domain.enums import UserConnectionStatusEnum
from app.domain.services.block import UserAlreadyBlockedError
from app.infrastructure.repository.connection import select_active_between
from app.infrastructure.repository.models import (
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)


def block_exists_between(
    user_a: UUID | ColumnElement[UUID], user_b: UUID | ColumnElement[UUID]
) -> ColumnElement[bool]:
    """SQL condition for "either user blocked the other".

    Accepts columns too, so list queries can filter rows in the database with
    the same rule BlockService.is_blocked_between applies to a single pair.
    """
    return exists().where(
        or_(
            and_(
                UserBlockModel.blocker_id == user_a,
                UserBlockModel.blocked_id == user_b,
            ),
            and_(
                UserBlockModel.blocker_id == user_b,
                UserBlockModel.blocked_id == user_a,
            ),
        )
    )


class SqlAlchemyBlockRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def exists_between(self, user_a: UUID, user_b: UUID) -> bool:
        return bool(self.db.scalar(select(block_exists_between(user_a, user_b))))

    def create(self, blocker_id: UUID, blocked_id: UUID) -> UserBlock:
        model = UserBlockModel(blocker_id=blocker_id, blocked_id=blocked_id)
        self.db.add(model)
        try:
            self.db.flush()
        except IntegrityError as error:
            self.db.rollback()
            raise UserAlreadyBlockedError from error

        connection = self.db.scalar(
            select_active_between(self.db, blocker_id, blocked_id)
            .where(UserConnectionModel.status != UserConnectionStatusEnum.REJECTED)
            .with_for_update()
        )
        if connection is not None:
            connection.deleted_at = datetime.now(UTC)

        self.db.commit()
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

    def delete(self, blocker_id: UUID, blocked_id: UUID) -> bool:
        result = self.db.execute(
            delete(UserBlockModel).where(
                UserBlockModel.blocker_id == blocker_id,
                UserBlockModel.blocked_id == blocked_id,
            )
        )
        self.db.commit()
        return result.rowcount > 0

    @staticmethod
    def _to_blocked_user(block: UserBlockModel, user: UserModel) -> BlockedUser:
        return BlockedUser(
            user_id=user.user_id,
            name=user.name,
            photo_url=user.profile_photo_url,
            blocked_at=block.created_at,
        )

    @staticmethod
    def _to_entity(model: UserBlockModel) -> UserBlock:
        return UserBlock(
            blocker_id=model.blocker_id,
            blocked_id=model.blocked_id,
            created_at=model.created_at,
        )
