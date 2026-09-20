from app.domain.entities import EventParticipant
from app.presentation.dtos import AcceptInviteOutput


class InviteAssembler:
    @staticmethod
    def to_accepted_dto(participant: EventParticipant) -> AcceptInviteOutput:
        if participant.participant_id is None:
            raise ValueError("A persisted participant must have an id")
        return AcceptInviteOutput(
            participant_id=participant.participant_id,
            event_id=participant.event_id,
            status=participant.status,
            updated_at=participant.updated_at,
        )
