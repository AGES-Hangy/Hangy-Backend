from typing import Protocol
from uuid import UUID

from app.domain.entities.user_profile import UserProfile

__all__ = [
    "UserNotFoundError",
    "UserProfileRepository",
    "UserProfileService",
]


class UserProfileRepository(Protocol):
    def get_profile(self, user_id: UUID) -> UserProfile | None: ...


class UserNotFoundError(Exception):
    """Raised when no active user exists with the given id."""


class UserProfileService:
    def __init__(self, repository: UserProfileRepository) -> None:
        self.repository = repository

    def get_profile(self, user_id: UUID) -> UserProfile:
        profile = self.repository.get_profile(user_id)
        if profile is None:
            raise UserNotFoundError
        return profile
