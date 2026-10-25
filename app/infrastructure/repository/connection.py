from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import (
    ConnectionSummary,
    PendingConnection,
    User,
    UserConnection,
)
from app.domain.enums import NotificationTypeEnum, UserConnectionStatusEnum
from app.domain.services.connection import ConnectionAlreadyExistsError
from app.domain.services.notification_dispatcher import NotificationDispatcher
from app.infrastructure.repository.models import (
    PersonProfileModel,
    UserConnectionModel,
    UserModel,
)
from app.infrastructure.repository.notification import (
    delete_connection_request_notifications,
)
from app.infrastructure.repository.user import SqlAlchemyUserRepository


def select_active_between(
    db: Session, user_a: UUID, user_b: UUID
) -> Select[tuple[UserConnectionModel]]:
    """Select the non-deleted connection of a pair, whoever requested it.

    Matches the shape of the uq_user_connection_active_pair partial index
    (LEAST/GREATEST on Postgres) so the lookup can use it, instead of an
    OR'd pair of ANDs that the planner can't.
    """
    low_id, high_id = sorted((user_a, user_b))
    # Postgres has no multi-arg min/max; SQLite has no least/greatest.
    if db.get_bind().dialect.name == "postgresql":
        least_fn, greatest_fn = func.least, func.greatest
    else:
        least_fn, greatest_fn = func.min, func.max
    return select(UserConnectionModel).where(
        UserConnectionModel.deleted_at.is_(None),
        least_fn(UserConnectionModel.requester_id, UserConnectionModel.receiver_id)
        == low_id,
        greatest_fn(UserConnectionModel.requester_id, UserConnectionModel.receiver_id)
        == high_id,
    )


class SqlAlchemyConnectionRepository:
    def __init__(self, db: Session, dispatcher: NotificationDispatcher) -> None:
        self.db = db
        self.dispatcher = dispatcher

    def get_by_id_for_update(self, connection_id: UUID) -> UserConnection | None:
        from app.infrastructure.repository.block_access import lock_user_pair

        pair = self.db.execute(
            select(
                UserConnectionModel.requester_id, UserConnectionModel.receiver_id
            ).where(UserConnectionModel.connection_id == connection_id)
        ).one_or_none()
        if pair is not None:
            lock_user_pair(self.db, *pair)
        model = self.db.scalar(
            select(UserConnectionModel)
            .where(
                UserConnectionModel.connection_id == connection_id,
                UserConnectionModel.deleted_at.is_(None),
            )
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
        model = self.db.scalar(select_active_between(self.db, user_a, user_b))
        return self._to_entity(model) if model is not None else None

    def list_pending_received(
        self,
        receiver_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_connection_id: UUID | None,
    ) -> list[PendingConnection]:
        """List the unanswered requests the user received, newest first.

        Requests from deleted accounts or from a user on either side of a
        block are left out, so the list never offers a request that can't be
        acted on.
        """
        # Imported here: block.py already imports this module at load time.
        from app.infrastructure.repository.block import block_exists_between

        stmt = (
            select(UserConnectionModel, UserModel.name, UserModel.profile_photo_url)
            .join(UserModel, UserModel.user_id == UserConnectionModel.requester_id)
            .where(
                UserConnectionModel.receiver_id == receiver_id,
                UserConnectionModel.status == UserConnectionStatusEnum.PENDING,
                UserConnectionModel.deleted_at.is_(None),
                UserModel.deleted_at.is_(None),
                ~block_exists_between(UserConnectionModel.requester_id, receiver_id),
            )
            .order_by(
                UserConnectionModel.created_at.desc(),
                UserConnectionModel.connection_id.desc(),
            )
        )

        if cursor_created_at is not None and cursor_connection_id is not None:
            stmt = stmt.where(
                or_(
                    UserConnectionModel.created_at < cursor_created_at,
                    (UserConnectionModel.created_at == cursor_created_at)
                    & (UserConnectionModel.connection_id < cursor_connection_id),
                )
            )

        rows = self.db.execute(stmt.limit(limit)).all()
        return [
            PendingConnection(
                connection_id=connection.connection_id,
                requester_id=connection.requester_id,
                requester_name=name,
                requester_photo_url=photo_url,
                created_at=connection.created_at,
            )
            for connection, name, photo_url in rows
        ]

    def list_confirmed(
        self,
        user_id: UUID,
        *,
        search: str | None,
        limit: int,
        cursor_connected_at: datetime | None,
        cursor_other_user_id: UUID | None,
    ) -> list[ConnectionSummary]:
        # Deferred import: app.infrastructure.repository.block imports
        # select_active_between from this module at module level, so a
        # top-level import here would be circular.
        from app.infrastructure.repository.block import block_exists_between

        other_user_id = case(
            (
                UserConnectionModel.requester_id == user_id,
                UserConnectionModel.receiver_id,
            ),
            else_=UserConnectionModel.requester_id,
        )
        stmt = (
            select(
                other_user_id.label("user_id"),
                UserModel.name.label("name"),
                UserModel.profile_photo_url.label("photo_url"),
                PersonProfileModel.city.label("city"),
                UserConnectionModel.updated_at.label("connected_at"),
            )
            .join(UserModel, UserModel.user_id == other_user_id)
            .outerjoin(PersonProfileModel, PersonProfileModel.user_id == other_user_id)
            .where(
                or_(
                    UserConnectionModel.requester_id == user_id,
                    UserConnectionModel.receiver_id == user_id,
                ),
                UserConnectionModel.status == UserConnectionStatusEnum.CONFIRMED,
                UserConnectionModel.deleted_at.is_(None),
                UserModel.deleted_at.is_(None),
                ~block_exists_between(other_user_id, user_id),
            )
            .order_by(UserConnectionModel.updated_at.desc(), other_user_id.desc())
        )
        if search:
            # Escape SQL LIKE wildcards in the raw input so a literal "_" or
            # "%" in the query matches itself instead of any/many characters.
            escaped_search = (
                search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            stmt = stmt.where(UserModel.name.ilike(f"%{escaped_search}%", escape="\\"))
        if cursor_connected_at is not None and cursor_other_user_id is not None:
            stmt = stmt.where(
                or_(
                    UserConnectionModel.updated_at < cursor_connected_at,
                    (UserConnectionModel.updated_at == cursor_connected_at)
                    & (other_user_id < cursor_other_user_id),
                )
            )
        rows = self.db.execute(stmt.limit(limit)).all()
        return [
            ConnectionSummary(
                user_id=row.user_id,
                name=row.name,
                photo_url=row.photo_url,
                city=row.city,
                connected_at=row.connected_at,
            )
            for row in rows
        ]

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

    def soft_delete(self, connection_id: UUID) -> None:
        model = self.db.scalar(
            select(UserConnectionModel).where(
                UserConnectionModel.connection_id == connection_id,
                UserConnectionModel.deleted_at.is_(None),
            )
        )
        if model is None:
            raise ValueError("A connection validated by the service must exist")
        model.deleted_at = datetime.now(UTC)
        delete_connection_request_notifications(self.db, connection_id)
        self.db.commit()

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
