from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    BusinessProfile,
    PersonProfile,
    Tag,
    User,
    UserProfile,
    UserProfileCounts,
)
from app.domain.enums import UserTypeEnum


class UserProfileRepository(Protocol):
    def get_person_profile(self, user_id: UUID) -> PersonProfile | None: ...

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None: ...

    def get_profile_counts(self, user_id: UUID) -> UserProfileCounts: ...


class UserProfileTagsRepository(Protocol):
    def list_user_tags(self, user_id: UUID) -> list[Tag]: ...


class UserProfileService:
    def __init__(
        self,
        repository: UserProfileRepository,
        tags_repository: UserProfileTagsRepository,
    ) -> None:
        self.repository = repository
        self.tags_repository = tags_repository

    def get_profile_for_user(
        self, user: User
    ) -> PersonProfile | BusinessProfile | None:
        if user.user_id is None:
            raise ValueError("An authenticated user must have an id")
        if user.user_type is UserTypeEnum.PERSONAL:
            return self.repository.get_person_profile(user.user_id)
        return self.repository.get_business_profile(user.user_id)

    def get_profile(self, user: User) -> UserProfile:
        """The profile screen header plus the counters of its tabs."""
        if user.user_id is None:
            raise ValueError("An authenticated user must have an id")
        # The user was already loaded (and checked as active) by authentication,
        # so only the tags and the counters still need the database.
        return UserProfile(
            user_id=user.user_id,
            name=user.name,
            description=user.description,
            photo_url=user.profile_photo_url,
            tags=tuple(self.tags_repository.list_user_tags(user.user_id)),
            counts=self.repository.get_profile_counts(user.user_id),
        )
