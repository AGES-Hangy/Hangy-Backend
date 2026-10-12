from typing import Protocol
from uuid import UUID

from app.domain.entities.user_profile import UserProfileData
from app.domain.services.block import BlockChecker


class UserNotFoundError(Exception):
    pass


class UserProfileRepository(Protocol):
    def get_profile(self, user_id: UUID, viewer_id: UUID) -> UserProfileData | None:
        pass


class UsersService:
    def __init__(
        self, repository: UserProfileRepository, block_checker: BlockChecker
    ) -> None:
        self.repository = repository
        self.block_checker = block_checker

    def get_profile(self, user_id: UUID, viewer_id: UUID) -> UserProfileData:
        # A block hides the profile from both sides, with the same error as a
        # missing user so neither can tell the two cases apart.
        if self.block_checker.is_blocked_between(user_id, viewer_id):
            raise UserNotFoundError()

        profile = self.repository.get_profile(user_id=user_id, viewer_id=viewer_id)

        if profile is None:
            raise UserNotFoundError()

        return profile


__all__ = ["UserProfileRepository", "UserNotFoundError", "UsersService"]
