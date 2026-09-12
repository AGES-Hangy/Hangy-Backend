from app.domain.entities import EventDetails
from app.presentation.dtos import (
    EventDetailsLocationOutput,
    EventDetailsOrganizerOutput,
    EventDetailsOutput,
    EventDetailsParticipantOutput,
    EventDetailsTagOutput,
    EventDetailsViewerOutput,
    EventParticipantsPreviewOutput,
)


class EventDetailsAssembler:
    @staticmethod
    def to_dto(details: EventDetails) -> EventDetailsOutput:
        event = details.event
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")

        preview = None
        if details.participants_preview is not None:
            preview = EventParticipantsPreviewOutput(
                count=details.participants_preview.count,
                items=[
                    EventDetailsParticipantOutput(
                        participant_id=participant.participant_id,
                        user_id=participant.user_id,
                        name=participant.name,
                        user_type=participant.user_type,
                        avatar_url=participant.avatar_url,
                        status=participant.status,
                        requested_at=participant.requested_at,
                    )
                    for participant in details.participants_preview.items
                ],
            )

        return EventDetailsOutput(
            event_id=event.event_id,
            title=event.event_title,
            description=event.event_description,
            event_date=event.starts_at,
            end_date=event.ends_at,
            location=EventDetailsLocationOutput(
                latitude=event.event_latitude,
                longitude=event.event_longitude,
            ),
            location_name=event.location_name,
            privacy=event.event_privacy,
            status=event.event_status,
            cover_photo_url=event.cover_photo_url,
            tags=[
                EventDetailsTagOutput(id=tag.tag_id, name=tag.tag_name)
                for tag in details.tags
                if tag.tag_id is not None
            ],
            organizer=EventDetailsOrganizerOutput(
                id=details.organizer.user_id,
                name=details.organizer.name,
                user_type=details.organizer.user_type,
            ),
            viewer=EventDetailsViewerOutput(
                is_organizer=details.viewer.is_organizer,
                participation_status=details.viewer.participation_status,
                can_see_participants=details.viewer.can_see_participants,
                available_action=details.viewer.available_action,
            ),
            participants_preview=preview,
        )
