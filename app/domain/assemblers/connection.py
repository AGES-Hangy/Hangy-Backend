from app.domain.entities import ConnectionsPage, ConnectionSummary, UserConnection
from app.presentation.dtos import (
    ConnectionsOutput,
    ConnectionSummaryOutput,
    SendConnectionRequestOutput,
)


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

    @staticmethod
    def to_connections_dto(page: ConnectionsPage) -> ConnectionsOutput:
        return ConnectionsOutput(
            items=[ConnectionAssembler._to_summary_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_summary_dto(summary: ConnectionSummary) -> ConnectionSummaryOutput:
        return ConnectionSummaryOutput(
            user_id=summary.user_id,
            name=summary.name,
            photo_url=summary.photo_url,
            city=summary.city,
            connected_at=summary.connected_at,
        )
