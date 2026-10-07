from uuid import UUID

from sqlalchemy import Uuid, and_, column, func, inspect, or_, select, table
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.tag import Tag
from app.domain.entities.user_profile import UserProfileData
from app.domain.enums import UserConnectionStatusEnum, UserTypeEnum
from app.infrastructure.repository.models import (
    UserConnectionModel,
    UserModel,
    user_follows,
)

USER_BLOCK_TABLE_NAME = "user_block"
user_block = table(
    USER_BLOCK_TABLE_NAME,
    column("blocker_id", Uuid),
    column("blocked_id", Uuid),
)


class SqlAlchemyUserProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_profile(self, user_id: UUID, viewer_id: UUID) -> UserProfileData | None:
        model = (
            self.db.execute(
                select(UserModel)
                .where(
                    UserModel.user_id == user_id,
                    UserModel.deleted_at.is_(None),
                )
                .options(joinedload(UserModel.tags))
            )
            .unique()
            .scalar_one_or_none()
        )

        if model is None:
            return None

        is_blocked = self._viewer_is_blocked(user_id=user_id, viewer_id=viewer_id)

        connections_count = 0
        is_following = False
        connection_status = None

        if model.user_type == UserTypeEnum.PERSONAL:
            connections_count = (
                self.db.scalar(
                    select(func.count(UserConnectionModel.connection_id)).where(
                        UserConnectionModel.status
                        == UserConnectionStatusEnum.CONFIRMED,
                        or_(
                            UserConnectionModel.requester_id == user_id,
                            UserConnectionModel.receiver_id == user_id,
                        ),
                    )
                )
                or 0
            )

            if viewer_id != user_id:
                connection_status = self.db.scalar(
                    select(UserConnectionModel.status).where(
                        or_(
                            and_(
                                UserConnectionModel.requester_id == viewer_id,
                                UserConnectionModel.receiver_id == user_id,
                            ),
                            and_(
                                UserConnectionModel.requester_id == user_id,
                                UserConnectionModel.receiver_id == viewer_id,
                            ),
                        )
                    )
                )
        else:
            connections_count = (
                self.db.scalar(
                    select(func.count())
                    .select_from(user_follows)
                    .where(user_follows.c.followed_business_id == user_id)
                )
                or 0
            )

            if viewer_id != user_id:
                is_following = (
                    self.db.scalar(
                        select(func.count())
                        .select_from(user_follows)
                        .where(
                            user_follows.c.follower_id == viewer_id,
                            user_follows.c.followed_business_id == user_id,
                        )
                    )
                    > 0
                )

        return UserProfileData(
            user_id=model.user_id,
            user_type=model.user_type,
            name=model.name,
            description=model.description,
            photo_url=model.profile_photo_url,
            tags=tuple(
                Tag(
                    tag_id=tag.tag_id,
                    tag_name=tag.tag_name,
                    tag_parent_id=tag.tag_parent_id,
                )
                for tag in sorted(
                    model.tags,
                    key=lambda tag: (
                        tag.tag_parent_id is not None,
                        tag.tag_name,
                        tag.tag_id,
                    ),
                )
            ),
            connection_status=connection_status,
            is_following=is_following,
            is_blocked=is_blocked,
            connections_count=connections_count,
        )

    def _viewer_is_blocked(self, user_id: UUID, viewer_id: UUID) -> bool:
        bind = self.db.get_bind()
        if not inspect(bind).has_table(USER_BLOCK_TABLE_NAME):
            return False

        return (
            self.db.scalar(
                select(func.count())
                .select_from(user_block)
                .where(
                    user_block.c.blocker_id == user_id,
                    user_block.c.blocked_id == viewer_id,
                )
            )
            > 0
        )


__all__ = ["SqlAlchemyUserProfileRepository"]
