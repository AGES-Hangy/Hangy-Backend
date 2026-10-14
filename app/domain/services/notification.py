from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Notification, UnreadNotificationCount
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

"""NotificationService — list, count and mark notifications for a user."""

__all__ = [
    "NotificationNotFoundError",
    "NotificationNotOwnedError",
    "NotificationRepository",
    "NotificationService",
]

# ---------------------------------------------------------------------------
# Repository protocol
# ---------------------------------------------------------------------------


class NotificationRepository(Protocol):
    def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
        unread_only: bool,
    ) -> list[Notification]: ...

    def mark_all_as_read(self, user_id: UUID) -> None: ...
    def count_unread(self, user_id: UUID) -> int: ...

    def get_by_id(self, notification_id: UUID) -> Notification | None: ...

    def mark_as_read(self, notification_id: UUID) -> None: ...


class NotificationNotFoundError(Exception):
    """Raised when no notification exists with the given id."""


class NotificationNotOwnedError(Exception):
    """Raised when the notification belongs to another user."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

_MIN_LIMIT = 1
_MAX_LIMIT = 100


class NotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

    def mark_all_as_read(self, user_id: UUID) -> None:
        self.repository.mark_all_as_read(user_id)

    def get_unread_count(self, user_id: UUID) -> UnreadNotificationCount:
        return UnreadNotificationCount(count=self.repository.count_unread(user_id))

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> None:
        notification = self.repository.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError
        if notification.user_id != user_id:
            raise NotificationNotOwnedError
        # Idempotent: an already read notification is a success, not an error.
        if not notification.read:
            self.repository.mark_as_read(notification_id)

    def list_notifications(
        self,
        user_id: UUID,
        *,
        limit: int = 20,
        cursor: str | None = None,
        unread_only: bool = False,
    ) -> tuple[list[Notification], str | None, int]:
        """Return (items, next_cursor, unread_count).

        Pagination is cursor-based on (created_at DESC, notification_id DESC)
        so pages are stable even as new rows arrive.
        """
        if not (_MIN_LIMIT <= limit <= _MAX_LIMIT):
            raise InvalidPaginationError(
                f"limit must be between {_MIN_LIMIT} and {_MAX_LIMIT}"
            )

        cursor_created_at: datetime | None = None
        cursor_id: UUID | None = None
        if cursor:
            cursor_created_at, cursor_id = decode_cursor(cursor)

        # Ask for one extra item to detect whether another page exists.
        items = self.repository.list_for_user(
            user_id,
            limit=limit + 1,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
            unread_only=unread_only,
        )

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor: str | None = None
        if has_more and items:
            last = items[-1]
            assert last.notification_id is not None
            next_cursor = encode_cursor(last.created_at, last.notification_id)

        unread_count = self.repository.count_unread(user_id)
        return items, next_cursor, unread_count
