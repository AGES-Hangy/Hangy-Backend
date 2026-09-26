from app.domain.entities import EventParticipant, EventParticipantsPage
from app.presentation.dtos import (
    EventParticipantItemOutput,
    EventParticipantsOutput,
    EventParticipantUserOutput,
    EventParticipationOutput,
)


class EventParticipantsAssembler:
    """Build the participants list response DTO from domain entities."""

    @staticmethod
    def to_dto(page: EventParticipantsPage) -> EventParticipantsOutput:
        counts = {"CONFIRMED": page.counts.confirmed}
        if page.counts.pending is not None:
            counts["PENDING"] = page.counts.pending

        return EventParticipantsOutput(
            items=[
                EventParticipantItemOutput(
                    participant_id=item.participant_id,
                    user=EventParticipantUserOutput(
                        id=item.user_id, name=item.user_name
                    ),
                    status=item.status,
                    joined_at=item.joined_at,
                )
                for item in page.items
            ],
            counts=counts,
            next_cursor=page.next_cursor,
        )


class EventParticipationAssembler:
    """Build the participation response DTO from a domain entity."""

    @staticmethod
    def to_dto(participant: EventParticipant) -> EventParticipationOutput:
        return EventParticipationOutput(
            participant_id=participant.participant_id,
            status=participant.status,
            joined_at=participant.joined_at,
        )
