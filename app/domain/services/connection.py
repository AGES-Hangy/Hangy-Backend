from typing import Protocol
from uuid import UUID

from app.domain.entities import UserConnection
from app.domain.enums import UserConnectionStatusEnum


class ConnectionRepository(Protocol):
    def get_by_id_for_update(self, connection_id: UUID) -> UserConnection | None: ...

    def create(self, requester_id: UUID, receiver_id: UUID) -> UserConnection: ...

    def accept(self, connection_id: UUID) -> UserConnection: ...

    def reject(self, connection_id: UUID) -> UserConnection: ...


class ConnectionNotFoundError(Exception):
    """Raised when the requested connection does not exist."""


class NotConnectionReceiverError(Exception):
    """Raised when someone other than the receiver tries to accept or reject."""


class InvalidConnectionStatusTransitionError(Exception):
    """Raised when the connection is not in PENDING state."""


class ConnectionService:
    def __init__(self, repository: ConnectionRepository) -> None:
        self.repository = repository

    def send_request(self, requester_id: UUID, receiver_id: UUID) -> UserConnection:
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
