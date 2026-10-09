from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import BusinessProfile, FollowedBusiness, User, UserFollow
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessRegistrationRepository,
)
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    UserFollowModel,
    UserModel,
)
from app.infrastructure.repository.user import SqlAlchemyUserRepository

__all__ = ["SqlAlchemyFollowRepository"]


class SqlAlchemyFollowRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_user(self, user_id: UUID) -> User | None:
        model = self.db.scalar(
            select(UserModel).where(
                UserModel.user_id == user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        return SqlAlchemyUserRepository._to_entity(model) if model else None

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None:
        model = self.db.scalar(
            select(BusinessProfileModel).where(BusinessProfileModel.user_id == user_id)
        )
        if model is None:
            return None
        return SqlAlchemyBusinessRegistrationRepository._to_entity(model)

    def get_follow(
        self, follower_id: UUID, followed_business_id: UUID
    ) -> UserFollow | None:
        model = self.db.scalar(
            select(UserFollowModel).where(
                UserFollowModel.follower_id == follower_id,
                UserFollowModel.followed_business_id == followed_business_id,
            )
        )
        return self._to_entity(model) if model else None

    def add(self, follow: UserFollow) -> None:
        self.db.add(
            UserFollowModel(
                follower_id=follow.follower_id,
                followed_business_id=follow.followed_business_id,
                created_at=follow.created_at,
            )
        )
        try:
            self.db.commit()
        except IntegrityError:
            # A concurrent request created the same (follower, business) pair
            # first. The composite PK keeps a single row; the outcome is the
            # same as an already-followed business.
            self.db.rollback()

    def remove(self, follower_id: UUID, followed_business_id: UUID) -> None:
        """Delete the follow row. Deleting a missing row is a no-op."""
        self.db.execute(
            delete(UserFollowModel).where(
                UserFollowModel.follower_id == follower_id,
                UserFollowModel.followed_business_id == followed_business_id,
            )
        )
        self.db.commit()

    def list_following(
        self,
        follower_id: UUID,
        *,
        limit: int,
        cursor_followed_at: datetime | None,
        cursor_business_id: UUID | None,
    ) -> list[FollowedBusiness]:
        """Businesses followed by ``follower_id``, newest follow first.

        Joins ``user`` and keeps only ``deleted_at IS NULL``: a soft-deleted
        account never shows up, even if a stale follow row is left behind.
        Kept apart from the service so the business-side follower listing
        (US11.3) can add a sibling query on the same table.
        """
        stmt = (
            select(UserFollowModel, UserModel)
            .join(UserModel, UserModel.user_id == UserFollowModel.followed_business_id)
            .where(
                UserFollowModel.follower_id == follower_id,
                UserModel.deleted_at.is_(None),
            )
            .order_by(
                UserFollowModel.created_at.desc(),
                UserFollowModel.followed_business_id.desc(),
            )
        )
        if cursor_followed_at is not None and cursor_business_id is not None:
            stmt = stmt.where(
                or_(
                    UserFollowModel.created_at < cursor_followed_at,
                    (UserFollowModel.created_at == cursor_followed_at)
                    & (UserFollowModel.followed_business_id < cursor_business_id),
                )
            )
        rows = self.db.execute(stmt.limit(limit)).all()
        return [self._to_followed_business(follow, user) for follow, user in rows]

    @staticmethod
    def _to_followed_business(
        follow: UserFollowModel, user: UserModel
    ) -> FollowedBusiness:
        return FollowedBusiness(
            user_id=user.user_id,
            business_name=user.name,
            photo_url=user.profile_photo_url,
            followed_at=follow.created_at,
        )

    @staticmethod
    def _to_entity(model: UserFollowModel) -> UserFollow:
        return UserFollow(
            follower_id=model.follower_id,
            followed_business_id=model.followed_business_id,
            created_at=model.created_at,
        )
