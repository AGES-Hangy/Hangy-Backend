from typing import Protocol
from uuid import UUID

from app.domain.entities.user_profile import UserProfileData


class UserNotFoundError(Exception):
    pass


class UserProfileRepository(Protocol):
    def get_profile(self, user_id: UUID, viewer_id: UUID) -> UserProfileData | None:
        pass


class UsersService:
    def __init__(self, repository: UserProfileRepository) -> None:
        self.repository = repository

    def get_profile(self, user_id: UUID, viewer_id: UUID) -> UserProfileData:
        profile = self.repository.get_profile(user_id=user_id, viewer_id=viewer_id)

        if profile is None:
            raise UserNotFoundError()

        if profile.is_blocked:
            raise UserNotFoundError()

        return profile


__all__ = ["UserProfileRepository", "UserNotFoundError", "UsersService"]
