from app.domain.entities import UserConnection
from app.presentation.dtos import SendConnectionRequestOutput


class ConnectionAssembler:
    @staticmethod
    def to_created_dto(connection: UserConnection) -> SendConnectionRequestOutput:
        if connection.connection_id is None:
            raise ValueError("A persisted connection must have an id")
        return SendConnectionRequestOutput(
            connection_id=connection.connection_id,
            requester_id=connection.requester_id,
            receiver_id=connection.receiver_id,
            status=connection.status,
            created_at=connection.created_at,
        )
