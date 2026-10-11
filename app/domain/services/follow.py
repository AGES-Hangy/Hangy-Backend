from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import BusinessProfile, User, UserFollow

__all__ = [
    "BusinessNotFoundError",
    "FollowRepository",
    "FollowService",
    "TargetNotBusinessError",
]


class FollowRepository(Protocol):
    def get_active_user(self, user_id: UUID) -> User | None: ...

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None: ...

    def get_follow(
        self, follower_id: UUID, followed_business_id: UUID
    ) -> UserFollow | None: ...

    def add(self, follow: UserFollow) -> None: ...

    def remove(self, follower_id: UUID, followed_business_id: UUID) -> None: ...


class BusinessNotFoundError(Exception):
    """There is no active account with this id (missing or soft-deleted)."""


class TargetNotBusinessError(Exception):
    """The account exists but is a personal profile, which cannot be followed."""


class FollowService:
    def __init__(self, repository: FollowRepository) -> None:
        self.repository = repository

    def follow(self, follower_id: UUID, business_id: UUID) -> None:
        """Follow a business right away: no approval, status or notification."""
        self.get_followable_business(business_id)
        if self.repository.get_follow(follower_id, business_id) is not None:
            # Idempotent: following someone already followed is a success.
            return
        self.repository.add(
            UserFollow(
                follower_id=follower_id,
                followed_business_id=business_id,
                created_at=datetime.now(UTC),
            )
        )

    def unfollow(self, follower_id: UUID, business_id: UUID) -> None:
        """Stop following a business. Idempotent: not following is a success."""
        self.get_followable_business(business_id)
        self.repository.remove(follower_id, business_id)

    def get_followable_business(self, business_id: UUID) -> BusinessProfile:
        """Resolve an active business or explain why it cannot be followed.

        Kept apart from ``follow`` so the business-side follower listing
        (US11.3) can reuse the same existence/type validation.
        """
        if self.repository.get_active_user(business_id) is None:
            raise BusinessNotFoundError
        profile = self.repository.get_business_profile(business_id)
        if profile is None:
            raise TargetNotBusinessError
        return profile
