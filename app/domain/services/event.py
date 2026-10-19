from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime
from logging import getLogger
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.entities import Event, EventParticipant, EventUpdate, NewEvent
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.domain.services.event_location import approximate_point
from app.domain.services.image_upload import ImageUploadService

logger = getLogger(__name__)

MAX_EVENT_TAGS = 5
MIN_LATITUDE, MAX_LATITUDE = -90.0, 90.0
MIN_LONGITUDE, MAX_LONGITUDE = -180.0, 180.0

VALID_TRANSITIONS: dict[EventParticipantStatusEnum, set[EventParticipantStatusEnum]] = {
    EventParticipantStatusEnum.PENDING: {
        EventParticipantStatusEnum.CONFIRMED,
        EventParticipantStatusEnum.REJECTED,
    },
    EventParticipantStatusEnum.CONFIRMED: {
        EventParticipantStatusEnum.REMOVED,
    },
}

NOTIFICATION_TYPE_BY_STATUS: dict[EventParticipantStatusEnum, NotificationTypeEnum] = {
    EventParticipantStatusEnum.CONFIRMED: NotificationTypeEnum.EVENT_REQUEST_APPROVED,
    EventParticipantStatusEnum.REJECTED: NotificationTypeEnum.EVENT_REQUEST_REJECTED,
    EventParticipantStatusEnum.REMOVED: NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
}


class EventRepository(Protocol):
    def add(self, event: NewEvent) -> Event: ...

    def find_existing_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]: ...

    def get_by_id_for_update(self, event_id: UUID) -> Event | None: ...

    def get_participant_for_update(
        self, event_id: UUID, participant_id: UUID
    ) -> EventParticipant | None: ...

    def update_participant_status_and_notify(
        self,
        event_id: UUID,
        participant_id: UUID,
        new_status: EventParticipantStatusEnum,
        notification_type: NotificationTypeEnum,
    ) -> EventParticipant: ...

    def cancel(self, event_id: UUID) -> Event: ...

    def get(self, event_id: UUID) -> Event | None: ...

    def update(self, event: Event, tag_ids: Collection[UUID] | None) -> Event: ...

    def get_confirmed_participant_ids(self, event_id: UUID) -> list[UUID]: ...

    def notify_event_updated(
        self, event_id: UUID, participant_ids: list[UUID]
    ) -> None: ...


class EventStartsInThePastError(Exception):
    """Raised when an event is published with a start date that already passed."""


class EventEndsBeforeItStartsError(Exception):
    """Raised when the end date of an event is not after its start date."""


class InvalidEventCoordinatesError(Exception):
    """Raised when the event coordinates fall outside the valid ranges."""


class InvalidCoverPhotoUrlError(Exception):
    """Raised when a new event cover does not belong to the image storage."""


class TooManyEventTagsError(Exception):
    """Raised when an event carries more tags than the domain allows."""


class EventTagNotFoundError(Exception):
    """Raised when an event references a tag that does not exist."""


class EventNotFoundError(Exception):
    """Raised when the requested event does not exist or is not visible."""


class EventParticipantNotFoundError(Exception):
    """Raised when a participant does not exist in an event."""


class NotEventOrganizerError(Exception):
    """Raised when someone other than the creator changes an event."""


class InvalidParticipantStatusTransitionError(Exception):
    """Raised when an invalid participant state transition is requested."""


class EventIsFullError(Exception):
    """Raised when approving a participant exceeds the event capacity."""


class EventAlreadyFinishedError(Exception):
    """Raised when an event that has already finished is changed."""


class EventsService:
    def __init__(
        self, repository: EventRepository, image_upload_service: ImageUploadService
    ) -> None:
        self.repository = repository
        self.image_upload_service = image_upload_service

    def create(self, event: NewEvent) -> Event:
        """Validate and publish an event, with its organizer already resolved."""
        if event.starts_at <= datetime.now(UTC):
            raise EventStartsInThePastError
        if event.ends_at <= event.starts_at:
            raise EventEndsBeforeItStartsError
        if not (
            MIN_LATITUDE <= event.event_latitude <= MAX_LATITUDE
            and MIN_LONGITUDE <= event.event_longitude <= MAX_LONGITUDE
        ):
            raise InvalidEventCoordinatesError
        if len(event.tag_ids) > MAX_EVENT_TAGS:
            raise TooManyEventTagsError

        self._validate_cover_photo_url(event.cover_photo_url)

        if event.tag_ids:
            existing = self.repository.find_existing_tag_ids(event.tag_ids)
            if len(existing) != len(event.tag_ids):
                raise EventTagNotFoundError

        # Computed for every event, whatever its privacy: who gets to see which
        # point is decided when the event is read, not here.
        event_id = uuid4()
        approx_latitude, approx_longitude = approximate_point(
            event_id, event.event_latitude, event.event_longitude
        )
        return self.repository.add(
            replace(
                event,
                event_id=event_id,
                approx_latitude=approx_latitude,
                approx_longitude=approx_longitude,
            )
        )

    def update_participant_status(
        self,
        event_id: UUID,
        participant_id: UUID,
        new_status: EventParticipantStatusEnum,
        requester_id: UUID,
    ) -> EventParticipant:
        """Approve, reject, or remove an event participant."""
        # Lock the event before inspecting state or capacity. The lock is held
        # until the repository commits the status and notification together.
        event = self.repository.get_by_id_for_update(event_id)
        if event is None:
            raise EventNotFoundError

        if event.event_creator_id != requester_id:
            raise NotEventOrganizerError

        participant = self.repository.get_participant_for_update(
            event_id, participant_id
        )
        if participant is None:
            raise EventParticipantNotFoundError

        allowed_next_statuses = VALID_TRANSITIONS.get(participant.status, set())
        if new_status not in allowed_next_statuses:
            raise InvalidParticipantStatusTransitionError

        notification_type = NOTIFICATION_TYPE_BY_STATUS.get(new_status)
        if notification_type is None:
            raise InvalidParticipantStatusTransitionError

        return self.repository.update_participant_status_and_notify(
            event_id=event_id,
            participant_id=participant_id,
            new_status=new_status,
            notification_type=notification_type,
        )

    def cancel(self, event_id: UUID, requester_id: UUID) -> Event:
        event = self.repository.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError
        if event.event_creator_id != requester_id:
            raise NotEventOrganizerError
        if event.event_status is EventStatusEnum.FINISHED:
            raise EventAlreadyFinishedError
        return self.repository.cancel(event_id)

    def update(self, event_id: UUID, organizer_id: UUID, changes: EventUpdate) -> Event:
        """Apply a partial update after enforcing the event editing rules."""
        event = self.repository.get(event_id)
        if event is None:
            raise EventNotFoundError
        if event.event_creator_id != organizer_id:
            raise NotEventOrganizerError
        if event.event_status is EventStatusEnum.FINISHED:
            raise EventAlreadyFinishedError

        starts_at = (
            changes.starts_at
            if "event_date" in changes.fields_to_update
            else event.starts_at
        )
        ends_at = (
            changes.ends_at if "end_date" in changes.fields_to_update else event.ends_at
        )
        if "event_date" in changes.fields_to_update and starts_at <= datetime.now(UTC):
            raise EventStartsInThePastError
        if ends_at <= starts_at:
            raise EventEndsBeforeItStartsError
        if "location" in changes.fields_to_update and not (
            MIN_LATITUDE <= changes.event_latitude <= MAX_LATITUDE
            and MIN_LONGITUDE <= changes.event_longitude <= MAX_LONGITUDE
        ):
            raise InvalidEventCoordinatesError

        cover_changed = (
            "cover_photo_url" in changes.fields_to_update
            and changes.cover_photo_url != event.cover_photo_url
        )
        if cover_changed:
            self._validate_cover_photo_url(changes.cover_photo_url)

        tag_ids: Collection[UUID] | None = None
        if "tag_ids" in changes.fields_to_update:
            tag_ids = changes.tag_ids
            if len(tag_ids) > MAX_EVENT_TAGS:
                raise TooManyEventTagsError
            if tag_ids:
                existing = self.repository.find_existing_tag_ids(tag_ids)
                if len(existing) != len(tag_ids):
                    raise EventTagNotFoundError

        # The approximate point only moves together with the real one, so
        # editing anything else can never be used to sample new offsets.
        approx_latitude, approx_longitude = (
            event.approx_latitude,
            event.approx_longitude,
        )
        if "location" in changes.fields_to_update:
            approx_latitude, approx_longitude = approximate_point(
                event_id, changes.event_latitude, changes.event_longitude
            )

        updated_event = Event(
            event_id=event.event_id,
            event_creator_id=event.event_creator_id,
            event_title=(
                changes.event_title
                if "title" in changes.fields_to_update
                else event.event_title
            ),
            event_latitude=(
                changes.event_latitude
                if "location" in changes.fields_to_update
                else event.event_latitude
            ),
            event_longitude=(
                changes.event_longitude
                if "location" in changes.fields_to_update
                else event.event_longitude
            ),
            approx_latitude=approx_latitude,
            approx_longitude=approx_longitude,
            starts_at=starts_at,
            ends_at=ends_at,
            event_status=event.event_status,
            event_privacy=event.event_privacy,
            created_at=event.created_at,
            updated_at=event.updated_at,
            event_description=(
                changes.event_description
                if "description" in changes.fields_to_update
                else event.event_description
            ),
            location_name=(
                changes.location_name
                if "location_name" in changes.fields_to_update
                else event.location_name
            ),
            location_neighborhood=(
                changes.location_neighborhood
                if "location_neighborhood" in changes.fields_to_update
                else event.location_neighborhood
            ),
            location_city=(
                changes.location_city
                if "location_city" in changes.fields_to_update
                else event.location_city
            ),
            max_participants=event.max_participants,
            cover_photo_url=(
                changes.cover_photo_url
                if "cover_photo_url" in changes.fields_to_update
                else event.cover_photo_url
            ),
            deleted_at=event.deleted_at,
        )
        updated_event = self.repository.update(updated_event, tag_ids)

        # The repository commits the new cover before the old object is deleted.
        if (
            cover_changed
            and event.cover_photo_url is not None
            and self.image_upload_service.owns(event.cover_photo_url)
        ):
            try:
                self.image_upload_service.delete(event.cover_photo_url)
            except Exception:
                logger.exception(
                    "Failed to delete previous cover for event %s", event_id
                )

        if {"event_date", "location"} & changes.fields_to_update:
            participant_ids = self.repository.get_confirmed_participant_ids(event_id)
            if participant_ids:
                self.repository.notify_event_updated(event_id, participant_ids)

        return updated_event

    def _validate_cover_photo_url(self, url: str | None) -> None:
        if url is not None and not self.image_upload_service.owns(url):
            raise InvalidCoverPhotoUrlError
