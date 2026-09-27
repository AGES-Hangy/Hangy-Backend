from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Notification

"""NotificationService — list, count and mark notifications for a user."""

__all__ = [
    "InvalidPaginationError",
    "NotificationNotFoundError",
    "NotificationRepository",
    "NotificationService",
    "decode_cursor",
    "encode_cursor",
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

    def count_unread(self, user_id: UUID) -> int: ...

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> bool:
        """Return True if the notification existed and belonged to user_id."""
        ...

    def mark_all_as_read(self, user_id: UUID) -> None: ...


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class NotificationNotFoundError(Exception):
    """Raised when a notification does not exist for the given user."""


class InvalidPaginationError(Exception):
    """Raised when limit is out of bounds or cursor is malformed."""


# ---------------------------------------------------------------------------
# Cursor helpers (opaque base64 string encoding created_at + id)
# ---------------------------------------------------------------------------

_CURSOR_SEP = "|"


def encode_cursor(created_at: datetime, notification_id: UUID) -> str:
    raw = f"{created_at.isoformat()}{_CURSOR_SEP}{notification_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_part, id_part = raw.split(_CURSOR_SEP, 1)
        return datetime.fromisoformat(ts_part), uuid.UUID(id_part)
    except Exception as exc:
        raise InvalidPaginationError("Malformed cursor") from exc


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

_MIN_LIMIT = 1
_MAX_LIMIT = 100


class NotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

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

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> None:
        found = self.repository.mark_as_read(notification_id, user_id)
        if not found:
            raise NotificationNotFoundError(
                f"Notification {notification_id} not found for user {user_id}"
            )

    def mark_all_as_read(self, user_id: UUID) -> None:
        self.repository.mark_all_as_read(user_id)
