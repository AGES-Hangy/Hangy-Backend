from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    EventDetails,
    EventDetailsData,
    EventDetailsViewer,
    EventParticipantsPreview,
)
from app.domain.enums import (
    EventAvailableActionEnum,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)

PARTICIPANTS_PREVIEW_LIMIT = 5


class EventDetailsRepository(Protocol):
    def get_details(
        self, event_id: UUID, viewer_id: UUID
    ) -> EventDetailsData | None: ...


class EventCancelledError(Exception):
    """Raised when a known event was cancelled and must render that state."""


class EventDetailsNotFoundError(Exception):
    """Raised when an event does not exist or is not visible to this viewer."""


class EventDetailsService:
    def __init__(self, repository: EventDetailsRepository) -> None:
        self.repository = repository

    def get_details(self, event_id: UUID, viewer_id: UUID) -> EventDetails:
        data = self.repository.get_details(event_id, viewer_id)
        if data is None or data.organizer_blocked_viewer:
            raise EventDetailsNotFoundError

        event = data.event
        is_organizer = event.event_creator_id == viewer_id
        participation_status = data.viewer_participation_status

        # A draft belongs only to its organizer. Invite-only events deliberately
        # use the same 404 as a missing event to avoid revealing their existence.
        if event.event_status is EventStatusEnum.DRAFT and not is_organizer:
            raise EventDetailsNotFoundError
        if (
            event.event_privacy is EventPrivacyEnum.INVITE_ONLY
            and not is_organizer
            and participation_status
            not in (
                EventParticipantStatusEnum.INVITED,
                EventParticipantStatusEnum.CONFIRMED,
            )
        ):
            raise EventDetailsNotFoundError
        if event.event_status is EventStatusEnum.CANCELLED:
            raise EventCancelledError

        can_see_participants = (
            event.event_privacy is EventPrivacyEnum.PUBLIC
            or is_organizer
            or participation_status is EventParticipantStatusEnum.CONFIRMED
        )
        viewer = EventDetailsViewer(
            is_organizer=is_organizer,
            participation_status=participation_status,
            can_see_participants=can_see_participants,
            available_action=self._available_action(
                event.event_status,
                event.event_privacy,
                participation_status,
                is_organizer,
            ),
        )
        preview = None
        if can_see_participants:
            preview = EventParticipantsPreview(
                count=data.confirmed_participants_count,
                items=data.confirmed_participants[:PARTICIPANTS_PREVIEW_LIMIT],
            )

        return EventDetails(
            event=event,
            tags=data.tags,
            organizer=data.organizer,
            viewer=viewer,
            participants_preview=preview,
        )

    @staticmethod
    def _available_action(
        event_status: EventStatusEnum,
        privacy: EventPrivacyEnum,
        participation_status: EventParticipantStatusEnum | None,
        is_organizer: bool,
    ) -> EventAvailableActionEnum:
        if is_organizer:
            return EventAvailableActionEnum.MANAGE
        if event_status is not EventStatusEnum.PUBLISHED:
            return EventAvailableActionEnum.NONE
        if participation_status is EventParticipantStatusEnum.CONFIRMED:
            return EventAvailableActionEnum.CANCEL_PRESENCE
        if participation_status is EventParticipantStatusEnum.INVITED:
            return EventAvailableActionEnum.ACCEPT_INVITE
        if participation_status is not None:
            return EventAvailableActionEnum.NONE
        if privacy is EventPrivacyEnum.PUBLIC:
            return EventAvailableActionEnum.CONFIRM
        if privacy is EventPrivacyEnum.PRIVATE:
            return EventAvailableActionEnum.REQUEST
        return EventAvailableActionEnum.NONE
