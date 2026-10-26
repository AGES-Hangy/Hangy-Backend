from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import BlockedUser, BlockedUsersPage, UserBlock
from app.domain.services.auth import UserRepository
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

DEFAULT_BLOCKED_USERS_LIMIT = 20
MAX_BLOCKED_USERS_LIMIT = 100


class BlockRepository(Protocol):
    def exists_between(self, user_a: UUID, user_b: UUID) -> bool: ...

    def create(self, blocker_id: UUID, blocked_id: UUID) -> UserBlock: ...

    def list_blocked(
        self, blocker_id: UUID, limit: int, after: tuple[datetime, UUID] | None
    ) -> list[BlockedUser]: ...

    def delete(self, blocker_id: UUID, blocked_id: UUID) -> bool: ...


class BlockChecker(Protocol):
    def is_blocked_between(self, user_a: UUID, user_b: UUID) -> bool: ...


class CannotBlockSelfError(Exception):
    """Raised when a user tries to block themselves."""


class BlockedUserNotFoundError(Exception):
    """Raised when the user to block does not exist or was deleted."""


class UserAlreadyBlockedError(Exception):
    """Raised when the blocker has already blocked the same user."""


class UserNotBlockedError(Exception):
    """Raised when the user to unblock is not blocked by the requester."""


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

        # create() serializes pair writes and atomically removes connections,
        # participations and notifications. Repeated blocks repair legacy
        # effects before retaining UserAlreadyBlockedError.
        return self.repository.create(blocker_id, blocked_id)

    def unblock(self, blocker_id: UUID, blocked_id: UUID) -> None:
        # Only the blocker's own row is removed; a block the other user placed
        # is not theirs to lift. The connection undone by the block is not
        # restored: the users have to connect again.
        if not self.repository.delete(blocker_id, blocked_id):
            raise UserNotBlockedError

    def is_blocked_between(self, user_a: UUID, user_b: UUID) -> bool:
        """Whether either user blocked the other.

        The block is one-sided, but its invisibility is mutual: profile and
        connection requests ask this single question instead of each checking
        one direction on their own.
        """
        return self.repository.exists_between(user_a, user_b)

    def list_blocked(
        self,
        blocker_id: UUID,
        limit: int = DEFAULT_BLOCKED_USERS_LIMIT,
        cursor: str | None = None,
    ) -> BlockedUsersPage:
        if not 1 <= limit <= MAX_BLOCKED_USERS_LIMIT:
            raise InvalidPaginationError("Limit out of bounds")
        after = decode_cursor(cursor) if cursor else None

        rows = self.repository.list_blocked(blocker_id, limit + 1, after)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.blocked_at, last.user_id)
        return BlockedUsersPage(items=tuple(rows), next_cursor=next_cursor)
