from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import BusinessProfile, User, UserFollow
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

    @staticmethod
    def _to_entity(model: UserFollowModel) -> UserFollow:
        return UserFollow(
            follower_id=model.follower_id,
            followed_business_id=model.followed_business_id,
            created_at=model.created_at,
        )
