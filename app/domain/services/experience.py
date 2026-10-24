import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    EventExperience,
    EventExperienceAccess,
    EventPhoto,
    EventPhotoListItem,
    EventPhotosPage,
    ExperiencePhotoAccess,
    NewEventExperience,
)
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.domain.services.image_upload import ImageUploadService
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

__all__ = [
    "DEFAULT_EVENT_PHOTOS_LIMIT",
    "MAX_EVENT_PHOTOS_LIMIT",
    "MIN_EVENT_PHOTOS_LIMIT",
    "ExperienceAlreadyExistsError",
    "ExperienceEventNotFinishedError",
    "ExperienceEventNotFoundError",
    "ExperienceParticipantNotConfirmedError",
    "ExperiencePhotoDeleteForbiddenError",
    "ExperiencePhotoNotFoundError",
    "ExperienceRepository",
    "ExperienceService",
]

logger = logging.getLogger(__name__)

DEFAULT_EVENT_PHOTOS_LIMIT = 30
MIN_EVENT_PHOTOS_LIMIT = 1
MAX_EVENT_PHOTOS_LIMIT = 100


class ExperienceRepository(Protocol):
    def get_access(
        self, event_id: UUID, user_id: UUID
    ) -> EventExperienceAccess | None: ...

    def get_access_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventExperienceAccess | None: ...

    def list_event_photos(
        self,
        event_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_photo_id: UUID | None,
    ) -> list[EventPhoto]: ...

    def add(
        self, participant_id: UUID, experience: NewEventExperience
    ) -> EventExperience | None: ...

    def get_photo_access(self, photo_id: UUID) -> ExperiencePhotoAccess | None: ...

    def soft_delete_photo(self, photo_id: UUID) -> bool: ...


class ExperienceEventNotFoundError(Exception):
    """The event does not exist or is not visible to this user."""


class ExperienceEventNotFinishedError(Exception):
    """The event is still in progress."""


class ExperienceParticipantNotConfirmedError(Exception):
    """The user is not a confirmed participant in this event."""


class ExperienceAlreadyExistsError(Exception):
    """A participant can create only one experience per event."""


class ExperiencePhotoNotFoundError(Exception):
    """The photo does not exist or was already removed."""


class ExperiencePhotoDeleteForbiddenError(Exception):
    """Only the photo author or the event organizer can remove a photo."""


class ExperienceService:
    def __init__(
        self,
        repository: ExperienceRepository,
        image_upload_service: ImageUploadService,
    ) -> None:
        self.repository = repository
        self.image_upload_service = image_upload_service

    def create(
        self, event_id: UUID, user_id: UUID, experience: NewEventExperience
    ) -> EventExperience:
        access = self.repository.get_access_for_update(event_id, user_id)
        if access is None:
            raise ExperienceEventNotFoundError

        event = access.event
        participant = access.participant
        if not self._is_visible(access, user_id):
            raise ExperienceEventNotFoundError
        if (
            participant is None
            or not self._is_confirmed(access)
            or participant.participant_id is None
        ):
            raise ExperienceParticipantNotConfirmedError

        ends_at = event.ends_at
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=UTC)
        if (
            event.event_status is not EventStatusEnum.FINISHED
            and ends_at > datetime.now(UTC)
        ):
            raise ExperienceEventNotFinishedError

        created = self.repository.add(participant.participant_id, experience)
        if created is None:
            raise ExperienceAlreadyExistsError
        return created

    def list_photos(
        self,
        event_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = DEFAULT_EVENT_PHOTOS_LIMIT,
        cursor: str | None = None,
    ) -> EventPhotosPage:
        if not MIN_EVENT_PHOTOS_LIMIT <= limit <= MAX_EVENT_PHOTOS_LIMIT:
            raise InvalidPaginationError(
                f"limit must be between {MIN_EVENT_PHOTOS_LIMIT} "
                f"and {MAX_EVENT_PHOTOS_LIMIT}"
            )

        cursor_created_at: datetime | None = None
        cursor_photo_id: UUID | None = None
        if cursor:
            cursor_created_at, cursor_photo_id = decode_cursor(cursor)
        # Product decision: the gallery of a PUBLIC event is open to any
        # authenticated user who can see the event (not only participants).
        # INVITE_ONLY events stay hidden from non-confirmed users, and so do
        # events the organizer blocked the viewer from (see _is_visible).
        access = self.repository.get_access(event_id, viewer_id)
        if access is None or not self._is_visible(access, viewer_id):
            raise ExperienceEventNotFoundError
        photos = self.repository.list_event_photos(
            event_id,
            limit=limit + 1,
            cursor_created_at=cursor_created_at,
            cursor_photo_id=cursor_photo_id,
        )

        has_more = len(photos) > limit
        page = photos[:limit]
        organizer_id = access.event.event_creator_id
        items = tuple(
            EventPhotoListItem(
                photo=photo,
                can_delete=viewer_id in (photo.author_id, organizer_id),
            )
            for photo in page
        )
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = encode_cursor(last.created_at, last.photo_id)

        return EventPhotosPage(items=items, next_cursor=next_cursor)

    def delete_photo(self, photo_id: UUID, user_id: UUID) -> None:
        photo = self.repository.get_photo_access(photo_id)
        if photo is None:
            raise ExperiencePhotoNotFoundError
        if user_id not in (photo.author_id, photo.organizer_id):
            raise ExperiencePhotoDeleteForbiddenError

        if not self.repository.soft_delete_photo(photo_id):
            raise ExperiencePhotoNotFoundError

        try:
            if self.image_upload_service.owns(photo.photo_url):
                self.image_upload_service.delete(photo.photo_url)
        except Exception:
            logger.exception("Failed to delete S3 object of photo %s", photo_id)

    @staticmethod
    def _is_confirmed(access: EventExperienceAccess) -> bool:
        participant = access.participant
        return (
            participant is not None
            and participant.status is EventParticipantStatusEnum.CONFIRMED
        )

    @staticmethod
    def _is_visible(access: EventExperienceAccess, user_id: UUID) -> bool:
        event = access.event
        if access.organizer_blocked_viewer or event.event_status in (
            EventStatusEnum.DRAFT,
            EventStatusEnum.CANCELLED,
        ):
            return False
        return not (
            event.event_privacy is EventPrivacyEnum.INVITE_ONLY
            and user_id != event.event_creator_id
            and not ExperienceService._is_confirmed(access)
        )