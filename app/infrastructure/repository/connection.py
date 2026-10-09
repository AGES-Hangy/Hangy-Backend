from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import User, UserConnection
from app.domain.enums import NotificationTypeEnum, UserConnectionStatusEnum
from app.domain.services.connection import ConnectionAlreadyExistsError
from app.domain.services.notification_dispatcher import NotificationDispatcher
from app.infrastructure.repository.models import UserConnectionModel, UserModel
from app.infrastructure.repository.models.user_block_model import (
    UserBlockModel,
)
from app.infrastructure.repository.user import SqlAlchemyUserRepository


class SqlAlchemyConnectionRepository:
    def __init__(self, db: Session, dispatcher: NotificationDispatcher) -> None:
        self.db = db
        self.dispatcher = dispatcher

    def get_by_id_for_update(self, connection_id: UUID) -> UserConnection | None:
        model = self.db.scalar(
            select(UserConnectionModel)
            .where(UserConnectionModel.connection_id == connection_id)
            .with_for_update()
        )
        return self._to_entity(model) if model is not None else None

    def get_active_user(self, user_id: UUID) -> User | None:
        model = self.db.scalar(
            select(UserModel).where(
                UserModel.user_id == user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        return SqlAlchemyUserRepository._to_entity(model) if model is not None else None

    def find_active_between(self, user_a: UUID, user_b: UUID) -> UserConnection | None:
        # Matches the shape of the uq_user_connection_active_pair partial
        # index (LEAST/GREATEST on Postgres) so the lookup can use it,
        # instead of an OR'd pair of ANDs that the planner can't.
        low_id, high_id = sorted((user_a, user_b))
        least_fn, greatest_fn = self._pair_functions()
        model = self.db.scalar(
            select(UserConnectionModel).where(
                UserConnectionModel.deleted_at.is_(None),
                least_fn(
                    UserConnectionModel.requester_id, UserConnectionModel.receiver_id
                )
                == low_id,
                greatest_fn(
                    UserConnectionModel.requester_id, UserConnectionModel.receiver_id
                )
                == high_id,
            )
        )
        return self._to_entity(model) if model is not None else None

    def _pair_functions(self):
        """Postgres has no multi-arg min/max; SQLite has no least/greatest."""
        if self.db.get_bind().dialect.name == "postgresql":
            return func.least, func.greatest
        return func.min, func.max

    def is_blocked(self, user_a: UUID, user_b: UUID) -> bool:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(UserBlockModel)
                .where(
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
            )
            > 0
        )

    def create(self, requester_id: UUID, receiver_id: UUID) -> UserConnection:
        model = UserConnectionModel(
            requester_id=requester_id,
            receiver_id=receiver_id,
            status=UserConnectionStatusEnum.PENDING,
        )
        self.db.add(model)
        try:
            self.db.flush()
        except IntegrityError as error:
            self.db.rollback()
            raise ConnectionAlreadyExistsError from error
        self.dispatcher.dispatch(
            NotificationTypeEnum.CONNECTION_REQUEST,
            recipient_id=receiver_id,
            actor_id=requester_id,
            connection_id=model.connection_id,
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
        self.dispatcher.dispatch(
            NotificationTypeEnum.CONNECTION_ACCEPTED,
            recipient_id=model.requester_id,
            actor_id=model.receiver_id,
            connection_id=connection_id,
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
