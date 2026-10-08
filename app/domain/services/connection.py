from typing import Protocol
from uuid import UUID

from app.domain.entities import User, UserConnection
from app.domain.enums import UserConnectionStatusEnum, UserTypeEnum


class ConnectionRepository(Protocol):
    def get_by_id_for_update(self, connection_id: UUID) -> UserConnection | None: ...

    def create(self, requester_id: UUID, receiver_id: UUID) -> UserConnection: ...

    def accept(self, connection_id: UUID) -> UserConnection: ...

    def reject(self, connection_id: UUID) -> UserConnection: ...

    def get_active_user(self, user_id: UUID) -> User | None: ...

    def find_active_between(
        self, user_a: UUID, user_b: UUID
    ) -> UserConnection | None: ...

    def is_blocked(self, user_a: UUID, user_b: UUID) -> bool: ...


class ConnectionNotFoundError(Exception):
    """Raised when the requested connection does not exist."""


class NotConnectionReceiverError(Exception):
    """Raised when someone other than the receiver tries to accept or reject."""


class InvalidConnectionStatusTransitionError(Exception):
    """Raised when the connection is not in PENDING state."""


class CannotConnectToSelfError(Exception):
    """Raised when a user tries to send a connection request to themselves."""


class ReceiverNotFoundError(Exception):
    """Raised when the receiver does not exist, or has blocked the requester.

    Both cases return the same error on purpose: the requester must not be
    able to tell a nonexistent user apart from one who blocked them.
    """


class ConnectionAlreadyExistsError(Exception):
    """Raised when a non-deleted connection already exists between the pair."""


class ConnectionService:
    def __init__(self, repository: ConnectionRepository) -> None:
        self.repository = repository

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
        if self.repository.is_blocked(requester_id, receiver_id):
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
