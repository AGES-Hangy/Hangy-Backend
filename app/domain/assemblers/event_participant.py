from app.domain.entities import EventParticipantsPage
from app.presentation.dtos import (
    EventParticipantItemOutput,
    EventParticipantsOutput,
    EventParticipantUserOutput,
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
