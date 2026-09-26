from typing import Protocol
from uuid import UUID

from app.domain.entities import BusinessProfile, PersonProfile, User
from app.domain.enums import UserTypeEnum


class UserProfileRepository(Protocol):
    def get_person_profile(self, user_id: UUID) -> PersonProfile | None: ...

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None: ...


class UserProfileService:
    def __init__(self, repository: UserProfileRepository) -> None:
        self.repository = repository

    def get_profile_for_user(
        self, user: User
    ) -> PersonProfile | BusinessProfile | None:
        if user.user_id is None:
            raise ValueError("An authenticated user must have an id")
        if user.user_type is UserTypeEnum.PERSONAL:
            return self.repository.get_person_profile(user.user_id)
        return self.repository.get_business_profile(user.user_id)
