from collections.abc import Collection
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    ProfileEvent,
    ProfileEventsPage,
    UserEvent,
    UserEventsPage,
)
from app.domain.enums import EventPrivacyEnum, EventStatusEnum, UserEventsTabEnum
from app.domain.services.auth import UserRepository
from app.domain.services.notification import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)
from app.domain.services.user_tags import UserNotFoundError

DEFAULT_USER_EVENTS_LIMIT = 20
MIN_USER_EVENTS_LIMIT = 1
MAX_USER_EVENTS_LIMIT = 100


class UserEventsRepository(Protocol):
    def list_for_user(
        self,
        user_id: UUID,
        tab: UserEventsTabEnum,
        *,
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[UserEvent]: ...


class InvalidUserEventsTabError(Exception):
    """Raised when the requested tab is not `confirmed` or `past`."""


class UserEventsService:
    def __init__(self, repository: UserEventsRepository) -> None:
        self.repository = repository

    def get_user_events(
        self,
        user_id: UUID,
        tab: str,
        *,
        limit: int = DEFAULT_USER_EVENTS_LIMIT,
        cursor: str | None = None,
    ) -> UserEventsPage:
        try:
            requested_tab = UserEventsTabEnum(tab)
        except ValueError as error:
            raise InvalidUserEventsTabError from error

        if not MIN_USER_EVENTS_LIMIT <= limit <= MAX_USER_EVENTS_LIMIT:
            raise InvalidPaginationError(
                f"limit must be between {MIN_USER_EVENTS_LIMIT} "
                f"and {MAX_USER_EVENTS_LIMIT}"
            )

        cursor_starts_at: datetime | None = None
        cursor_event_id: UUID | None = None
        if cursor:
            cursor_starts_at, cursor_event_id = decode_cursor(cursor)

        events = self.repository.list_for_user(
            user_id,
            requested_tab,
            limit=limit + 1,
            cursor_starts_at=cursor_starts_at,
            cursor_event_id=cursor_event_id,
        )

        has_more = len(events) > limit
        items = events[:limit]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(last.starts_at, last.event_id)

        return UserEventsPage(items=tuple(items), next_cursor=next_cursor)


# GET /users/{user_id}/events: the events a user created or confirmed presence
# in. Someone else sees only these; past events are listed too, so FINISHED
# stays alongside PUBLISHED, and DRAFT/CANCELLED never leave the owner's view.
MAX_PROFILE_EVENTS_LIMIT = 50
MAX_PROFILE_EVENTS_CURSOR_LENGTH = 200
PUBLIC_PROFILE_PRIVACIES = (EventPrivacyEnum.PUBLIC,)
PUBLIC_PROFILE_STATUSES = (EventStatusEnum.PUBLISHED, EventStatusEnum.FINISHED)


class ProfileEventsRepository(Protocol):
    def user_blocked_viewer(self, user_id: UUID, viewer_id: UUID) -> bool: ...

    def list_for_profile(
        self,
        user_id: UUID,
        viewer_id: UUID,
        *,
        privacies: Collection[EventPrivacyEnum] | None,
        statuses: Collection[EventStatusEnum] | None,
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[ProfileEvent]: ...


class ProfileEventsService:
    """List the events shown on a profile, honoring privacy and blocks."""

    def __init__(
        self,
        user_repository: UserRepository,
        repository: ProfileEventsRepository,
    ) -> None:
        self.user_repository = user_repository
        self.repository = repository

    def get_profile_events(
        self,
        user_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = DEFAULT_USER_EVENTS_LIMIT,
        cursor: str | None = None,
    ) -> ProfileEventsPage:
        is_owner = user_id == viewer_id
        if not is_owner:
            user = self.user_repository.get_by_id(user_id)
            # A block answers exactly like a missing account: telling them
            # apart would confirm to the blocked viewer that the profile exists.
            if (
                user is None
                or user.deleted_at is not None
                or self.repository.user_blocked_viewer(user_id, viewer_id)
            ):
                raise UserNotFoundError

        cursor_starts_at: datetime | None = None
        cursor_event_id: UUID | None = None
        if cursor:
            cursor_starts_at, cursor_event_id = decode_cursor(cursor)

        events = self.repository.list_for_profile(
            user_id,
            viewer_id,
            # None leaves the filter out: owners see all of their own events.
            privacies=None if is_owner else PUBLIC_PROFILE_PRIVACIES,
            statuses=None if is_owner else PUBLIC_PROFILE_STATUSES,
            limit=limit + 1,
            cursor_starts_at=cursor_starts_at,
            cursor_event_id=cursor_event_id,
        )

        has_more = len(events) > limit
        items = events[:limit]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(last.starts_at, last.event_id)

        return ProfileEventsPage(items=tuple(items), next_cursor=next_cursor)
