"""Cursor pagination helpers shared by the services that list with a cursor."""

import base64
import uuid
from datetime import datetime
from uuid import UUID

__all__ = [
    "InvalidPaginationError",
    "decode_cursor",
    "decode_name_cursor",
    "encode_cursor",
    "encode_name_cursor",
]

_CURSOR_SEP = "|"


class InvalidPaginationError(Exception):
    """Raised when limit is out of bounds or cursor is malformed."""


def encode_cursor(timestamp: datetime, item_id: UUID) -> str:
    """Opaque base64 cursor encoding a timestamp and the item's id."""
    raw = f"{timestamp.isoformat()}{_CURSOR_SEP}{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_part, id_part = raw.split(_CURSOR_SEP, 1)
        return datetime.fromisoformat(ts_part), uuid.UUID(id_part)
    except Exception as exc:
        raise InvalidPaginationError("Malformed cursor") from exc


def encode_name_cursor(name: str, item_id: UUID) -> str:
    """Opaque base64 cursor encoding a display name and the item's id."""
    raw = f"{name}{_CURSOR_SEP}{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_name_cursor(cursor: str) -> tuple[str, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        name_part, id_part = raw.rsplit(_CURSOR_SEP, 1)
        if not name_part.strip() or "\x00" in name_part:
            raise ValueError("Invalid name in cursor")
        return name_part, uuid.UUID(id_part)
    except Exception as exc:
        raise InvalidPaginationError("Malformed cursor") from exc
