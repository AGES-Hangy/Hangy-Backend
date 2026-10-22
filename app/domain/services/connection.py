from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    ConnectionsPage,
    ConnectionSummary,
    PendingConnection,
    PendingConnectionsPage,
    User,
    UserConnection,
)
from app.domain.enums import UserConnectionStatusEnum, UserTypeEnum
from app.domain.services.block import BlockChecker
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

DEFAULT_CONNECTIONS_LIMIT = 20
MIN_CONNECTIONS_LIMIT = 1
MAX_CONNECTIONS_LIMIT = 100


class ConnectionRepository(Protocol):
    def get_by_id_for_update(self, connection_id: UUID) -> UserConnection | None: ...

    def create(self, requester_id: UUID, receiver_id: UUID) -> UserConnection: ...

    def accept(self, connection_id: UUID) -> UserConnection: ...

    def reject(self, connection_id: UUID) -> UserConnection: ...

    def soft_delete(self, connection_id: UUID) -> None: ...

    def get_active_user(self, user_id: UUID) -> User | None: ...

    def find_active_between(
        self, user_a: UUID, user_b: UUID
    ) -> UserConnection | None: ...

    def list_pending_received(
        self,
        receiver_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_connection_id: UUID | None,
    ) -> list[PendingConnection]: ...

    def list_confirmed(
        self,
        user_id: UUID,
        *,
        search: str | None,
        limit: int,
        cursor_connected_at: datetime | None,
        cursor_other_user_id: UUID | None,
    ) -> list[ConnectionSummary]: ...


class ConnectionNotFoundError(Exception):
    """Raised when the requested connection does not exist."""


class NotConnectionReceiverError(Exception):
    """Raised when someone other than the receiver tries to accept or reject."""


class NotConnectionParticipantError(Exception):
    """Raised when someone who is neither requester nor receiver undoes it."""


class InvalidConnectionStatusTransitionError(Exception):
    """Raised when the connection is not in PENDING state."""


class CannotConnectToSelfError(Exception):
    """Raised when a user tries to send a connection request to themselves."""


class ReceiverNotFoundError(Exception):
    """Raised when the receiver does not exist, or a block exists between the pair.

    Both cases return the same error on purpose: the requester must not be
    able to tell a nonexistent user apart from one who blocked them.
    """


class ConnectionAlreadyExistsError(Exception):
    """Raised when a non-deleted connection already exists between the pair."""


class ConnectionService:
    def __init__(
        self, repository: ConnectionRepository, block_checker: BlockChecker
    ) -> None:
        self.repository = repository
        self.block_checker = block_checker

    def send_request(self, requester_id: UUID, receiver_id: UUID) -> UserConnection:
        if requester_id == receiver_id:
            raise CannotConnectToSelfError
        receiver = self.repository.get_active_user(receiver_id)
        # A business receiver is folded into the same "not found" error as a
        # missing or blocking one: connections are personal-only (US8.3 adds
        # establishments later), and the requester should not learn the
        # receiver exists as a business account.
        if receiver is None or receiver.user_type is not UserTypeEnum.PERSONAL:
            raise ReceiverNotFoundError
        if self.block_checker.is_blocked_between(requester_id, receiver_id):
            raise ReceiverNotFoundError
        if self.repository.find_active_between(requester_id, receiver_id) is not None:
            raise ConnectionAlreadyExistsError
        # create() catches the unique-index violation itself and raises the
        # same ConnectionAlreadyExistsError if a concurrent request won the
        # race between the check above and this insert.
        return self.repository.create(requester_id, receiver_id)

    def accept(self, connection_id: UUID, actor_id: UUID) -> UserConnection:
        connection = self.repository.get_by_id_for_update(connection_id)
        if connection is None:
            raise ConnectionNotFoundError
        if connection.receiver_id != actor_id:
            raise NotConnectionReceiverError
        if connection.status is not UserConnectionStatusEnum.PENDING:
            raise InvalidConnectionStatusTransitionError
        return self.repository.accept(connection_id)

    def reject(self, connection_id: UUID, actor_id: UUID) -> UserConnection:
        connection = self.repository.get_by_id_for_update(connection_id)
        if connection is None:
            raise ConnectionNotFoundError
        if connection.receiver_id != actor_id:
            raise NotConnectionReceiverError
        if connection.status is not UserConnectionStatusEnum.PENDING:
            raise InvalidConnectionStatusTransitionError
        return self.repository.reject(connection_id)

    def undo_connection(self, connection_id: UUID, actor_id: UUID) -> None:
        """Undo a connection or cancel a pending request.

        Both sides use the same operation. It is a soft delete (`deleted_at`),
        not a new status, so the pair is freed for a new request. It is
        silent on purpose: no notification is dispatched.
        """
        connection = self.repository.get_by_id_for_update(connection_id)
        if connection is None:
            raise ConnectionNotFoundError
        if actor_id not in (connection.requester_id, connection.receiver_id):
            raise NotConnectionParticipantError
        self.repository.soft_delete(connection_id)

    def get_pending_requests(
        self,
        user_id: UUID,
        *,
        limit: int = DEFAULT_CONNECTIONS_LIMIT,
        cursor: str | None = None,
    ) -> PendingConnectionsPage:
        if not MIN_CONNECTIONS_LIMIT <= limit <= MAX_CONNECTIONS_LIMIT:
            raise InvalidPaginationError(
                f"limit must be between {MIN_CONNECTIONS_LIMIT} "
                f"and {MAX_CONNECTIONS_LIMIT}"
            )

        cursor_created_at: datetime | None = None
        cursor_connection_id: UUID | None = None
        if cursor:
            cursor_created_at, cursor_connection_id = decode_cursor(cursor)

        requests = self.repository.list_pending_received(
            user_id,
            limit=limit + 1,
            cursor_created_at=cursor_created_at,
            cursor_connection_id=cursor_connection_id,
        )

        has_more = len(requests) > limit
        items = requests[:limit]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.connection_id)

        return PendingConnectionsPage(items=tuple(items), next_cursor=next_cursor)

    def list_connections(
        self,
        user_id: UUID,
        *,
        search: str | None = None,
        limit: int = DEFAULT_CONNECTIONS_LIMIT,
        cursor: str | None = None,
    ) -> ConnectionsPage:
        if not MIN_CONNECTIONS_LIMIT <= limit <= MAX_CONNECTIONS_LIMIT:
            raise InvalidPaginationError(
                f"limit must be between {MIN_CONNECTIONS_LIMIT} "
                f"and {MAX_CONNECTIONS_LIMIT}"
            )

        cursor_connected_at: datetime | None = None
        cursor_other_user_id: UUID | None = None
        if cursor:
            cursor_connected_at, cursor_other_user_id = decode_cursor(cursor)

        items = self.repository.list_confirmed(
            user_id,
            search=search,
            limit=limit + 1,
            cursor_connected_at=cursor_connected_at,
            cursor_other_user_id=cursor_other_user_id,
        )

        has_more = len(items) > limit
        items = items[:limit]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(last.connected_at, last.user_id)

        return ConnectionsPage(items=tuple(items), next_cursor=next_cursor)
