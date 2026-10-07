from uuid import UUID

from app.presentation.dtos import SendConnectionRequestInput


class ConnectionMapper:
    @staticmethod
    def to_receiver_id(dto: SendConnectionRequestInput) -> UUID:
        return dto.receiver_id
