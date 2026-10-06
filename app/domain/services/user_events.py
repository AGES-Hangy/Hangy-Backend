from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import UserEvent, UserEventsPage
from app.domain.enums import UserEventsTabEnum
from app.domain.services.notification import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

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