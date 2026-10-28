"""AuditLogService — list recorded admin actions, newest first."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import AuditLogEntry
from app.domain.enums import AuditTargetTypeEnum
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

__all__ = ["AuditLogReadRepository", "AuditLogService"]

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20


class AuditLogReadRepository(Protocol):
    def list_entries(
        self,
        *,
        target_type: AuditTargetTypeEnum | None,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
    ) -> list[AuditLogEntry]: ...


class AuditLogService:
    def __init__(self, repository: AuditLogReadRepository) -> None:
        self.repository = repository

    def list_audit_log(
        self,
        *,
        target_type: AuditTargetTypeEnum | None = None,
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> tuple[list[AuditLogEntry], str | None]:
        """Return (items, next_cursor), newest first.

        Pagination is cursor-based on (created_at DESC, audit_log_id DESC) so
        pages are stable even as new rows arrive.
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
        items = self.repository.list_entries(
            target_type=target_type,
            limit=limit + 1,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor: str | None = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.audit_log_id)

        return items, next_cursor
