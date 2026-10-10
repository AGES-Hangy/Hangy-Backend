from dataclasses import replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import User, UserEvent, UserEventsPage, UserEventsTabs
from app.domain.enums import UserEventsTabEnum, UserTypeEnum
from app.domain.services.auth import UserRepository
from app.domain.services.notification import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)
from app.domain.services.users import UserNotFoundError

DEFAULT_USER_EVENTS_LIMIT = 20
MIN_USER_EVENTS_LIMIT = 1
MAX_USER_EVENTS_LIMIT = 100

# GET /users/me/events predates the profile tabs: it only ever served these,
# and `past` is what it calls `history`.
CURRENT_USER_TABS = {
    UserEventsTabEnum.CONFIRMED: UserEventsTabEnum.CONFIRMED,
    UserEventsTabEnum.PAST: UserEventsTabEnum.HISTORY,
    UserEventsTabEnum.HISTORY: UserEventsTabEnum.HISTORY,
}
# What anyone may see on a profile. `interests` and `confirmed` are a personal
# account's own plans, so they stay with the owner.
PUBLIC_PROFILE_TABS = (UserEventsTabEnum.HISTORY, UserEventsTabEnum.CREATED)
PERSONAL_OWNER_TABS = (
    *PUBLIC_PROFILE_TABS,
    UserEventsTabEnum.INTERESTS,
    UserEventsTabEnum.CONFIRMED,
)


class UserEventsRepository(Protocol):
    def user_blocked_viewer(self, user_id: UUID, viewer_id: UUID) -> bool: ...

    def list_for_user(
        self,
        user_id: UUID,
        tab: UserEventsTabEnum,
        *,
        viewer_id: UUID,
        public_only: bool,
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[UserEvent]: ...


class InvalidUserEventsTabError(Exception):
    """Raised when the tab is unknown, not shown to the viewer or missing."""


class UserEventsService:
    def __init__(
        self,
        repository: UserEventsRepository,
        user_repository: UserRepository,
    ) -> None:
        self.repository = repository
        self.user_repository = user_repository

    def get_user_events(
        self,
        user_id: UUID,
        tab: str,
        *,
        limit: int = DEFAULT_USER_EVENTS_LIMIT,
        cursor: str | None = None,
    ) -> UserEventsPage:
        try:
            requested_tab = CURRENT_USER_TABS[UserEventsTabEnum(tab)]
        except (ValueError, KeyError) as error:
            raise InvalidUserEventsTabError from error

        self._validate_limit(limit)
        return self._get_page(
            user_id,
            requested_tab,
            viewer_id=user_id,
            limit=limit,
            cursor=cursor,
        )

    def get_profile_events(
        self,
        user_id: UUID,
        viewer: User,
        *,
        tab: str | None = None,
        limit: int = DEFAULT_USER_EVENTS_LIMIT,
        cursor: str | None = None,
    ) -> UserEventsTabs:
        """List a profile's events by tab, as far as the viewer may see them.

        Without `tab` every allowed tab brings its first page. `tab` and
        `cursor` go together and continue a single tab, leaving the rest None.
        """
        if viewer.user_id is None:
            raise ValueError("A persisted user must have an id")
        self._validate_limit(limit)

        is_owner = user_id == viewer.user_id
        owner = viewer if is_owner else self._get_visible_user(user_id, viewer.user_id)
        allowed_tabs = (
            PERSONAL_OWNER_TABS
            if is_owner and owner.user_type is UserTypeEnum.PERSONAL
            else PUBLIC_PROFILE_TABS
        )

        if (tab is None) != (cursor is None):
            raise InvalidUserEventsTabError
        requested_tabs = allowed_tabs
        if tab is not None:
            try:
                requested_tab = UserEventsTabEnum(tab)
            except ValueError as error:
                raise InvalidUserEventsTabError from error
            if requested_tab not in allowed_tabs:
                raise InvalidUserEventsTabError
            requested_tabs = (requested_tab,)

        pages = {
            requested_tab.value: self._get_page(
                user_id,
                requested_tab,
                viewer_id=viewer.user_id,
                limit=limit,
                cursor=cursor,
            )
            for requested_tab in requested_tabs
        }
        return UserEventsTabs(**pages)

    def _get_visible_user(self, user_id: UUID, viewer_id: UUID) -> User:
        user = self.user_repository.get_by_id(user_id)
        # A block answers exactly like a missing account: telling them apart
        # would confirm to the blocked viewer that the profile exists.
        if (
            user is None
            or user.deleted_at is not None
            or self.repository.user_blocked_viewer(user_id, viewer_id)
        ):
            raise UserNotFoundError
        return user

    def _get_page(
        self,
        user_id: UUID,
        tab: UserEventsTabEnum,
        *,
        viewer_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> UserEventsPage:
        cursor_starts_at: datetime | None = None
        cursor_event_id: UUID | None = None
        if cursor:
            cursor_starts_at, cursor_event_id = decode_cursor(cursor)

        is_owner = user_id == viewer_id
        events = self.repository.list_for_user(
            user_id,
            tab,
            viewer_id=viewer_id,
            public_only=not is_owner,
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
        if not is_owner:
            # Whether the owner is going is theirs to know, not the visitor's.
            items = [replace(item, participation_status=None) for item in items]

        return UserEventsPage(items=tuple(items), next_cursor=next_cursor)

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not MIN_USER_EVENTS_LIMIT <= limit <= MAX_USER_EVENTS_LIMIT:
            raise InvalidPaginationError(
                f"limit must be between {MIN_USER_EVENTS_LIMIT} "
                f"and {MAX_USER_EVENTS_LIMIT}"
            )
