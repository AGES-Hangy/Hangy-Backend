from typing import Protocol
from uuid import UUID

from app.domain.entities import UserBlock
from app.domain.services.auth import UserRepository


class BlockRepository(Protocol):
    def exists_between(self, user_a: UUID, user_b: UUID) -> bool: ...

    def create(self, blocker_id: UUID, blocked_id: UUID) -> UserBlock: ...


class CannotBlockSelfError(Exception):
    """Raised when a user tries to block themselves."""


class BlockedUserNotFoundError(Exception):
    """Raised when the user to block does not exist or was deleted."""


class BlockService:
    def __init__(
        self, repository: BlockRepository, user_repository: UserRepository
    ) -> None:
        self.repository = repository
        self.user_repository = user_repository

    def block(self, blocker_id: UUID, blocked_id: UUID) -> UserBlock:
        if blocker_id == blocked_id:
            raise CannotBlockSelfError

        target = self.user_repository.get_by_id(blocked_id)
        if target is None or target.deleted_at is not None:
            raise BlockedUserNotFoundError

        return self.repository.create(blocker_id, blocked_id)

    def is_blocked_between(self, user_a: UUID, user_b: UUID) -> bool:
        return self.repository.exists_between(user_a, user_b)
