from app.domain.entities import (
    ConnectionsPage,
    ConnectionSummary,
    PendingConnection,
    PendingConnectionsPage,
    UserConnection,
)
from app.presentation.dtos import (
    AnswerConnectionRequestOutput,
    ConnectionsOutput,
    ConnectionSummaryOutput,
    PendingConnectionOutput,
    PendingConnectionsOutput,
    PendingConnectionUserOutput,
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
    def to_answered_dto(connection: UserConnection) -> AnswerConnectionRequestOutput:
        if connection.connection_id is None:
            raise ValueError("A persisted connection must have an id")
        return AnswerConnectionRequestOutput(
            connection_id=connection.connection_id,
            requester_id=connection.requester_id,
            receiver_id=connection.receiver_id,
            status=connection.status,
            updated_at=connection.updated_at,
        )

    @staticmethod
    def to_pending_dto(page: PendingConnectionsPage) -> PendingConnectionsOutput:
        return PendingConnectionsOutput(
            items=[
                ConnectionAssembler._to_pending_item_dto(item) for item in page.items
            ],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_pending_item_dto(item: PendingConnection) -> PendingConnectionOutput:
        return PendingConnectionOutput(
            connection_id=item.connection_id,
            user=PendingConnectionUserOutput(
                id=item.requester_id,
                name=item.requester_name,
                photo_url=item.requester_photo_url,
            ),
            created_at=item.created_at,
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
