from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AdminUserDetail,
    AdminUserDetailRecord,
    AdminUserItem,
    AdminUserRecord,
    AdminUsersPage,
)
from app.domain.enums import ModerationStatusEnum
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

DEFAULT_ADMIN_USERS_LIMIT = 20
MIN_ADMIN_USERS_LIMIT = 1
MAX_ADMIN_USERS_LIMIT = 100
MAX_ADMIN_USERS_SEARCH_LENGTH = 100


class AdminUsersRepository(Protocol):
    def list_users(
        self,
        now: datetime,
        status: ModerationStatusEnum | None,
        search: str | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[AdminUserRecord]: ...

    def get_detail(self, user_id: UUID) -> AdminUserDetailRecord | None: ...


class AdminUserNotFoundError(Exception):
    """Raised when user_id matches no active account."""


def derive_moderation_status(
    banned_at: datetime | None, suspended_until: datetime | None, now: datetime
) -> ModerationStatusEnum:
    """A ban wins over a suspension; an elapsed suspension is just ACTIVE.

    The repository filters by status with the same rule in SQL, so the two
    must change together.
    """
    if banned_at is not None:
        return ModerationStatusEnum.BANNED
    if suspended_until is not None and _as_utc(suspended_until) > now:
        return ModerationStatusEnum.SUSPENDED
    return ModerationStatusEnum.ACTIVE


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AdminUsersService:
    def __init__(self, repository: AdminUsersRepository) -> None:
        self.repository = repository

    def get_users(
        self,
        status: ModerationStatusEnum | None = None,
        search: str | None = None,
        limit: int = DEFAULT_ADMIN_USERS_LIMIT,
        cursor: str | None = None,
        now: datetime | None = None,
    ) -> AdminUsersPage:
        if not MIN_ADMIN_USERS_LIMIT <= limit <= MAX_ADMIN_USERS_LIMIT:
            raise InvalidPaginationError("Limit out of bounds")
        after = decode_cursor(cursor) if cursor else None
        now = now or datetime.now(UTC)
        search = (search or "").strip() or None

        rows = self.repository.list_users(now, status, search, limit + 1, after)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.created_at, last.user_id)
        return AdminUsersPage(
            items=tuple(self._to_item(row, now) for row in rows),
            next_cursor=next_cursor,
        )

    def get_user_detail(
        self, user_id: UUID, now: datetime | None = None
    ) -> AdminUserDetail:
        now = now or datetime.now(UTC)
        record = self.repository.get_detail(user_id)
        if record is None:
            raise AdminUserNotFoundError

        status = derive_moderation_status(record.banned_at, record.suspended_until, now)
        return AdminUserDetail(
            user_id=record.user_id,
            name=record.name,
            email=record.email,
            member_since=_as_utc(record.created_at).date(),
            moderation_status=status,
            banned_at=_as_utc(record.banned_at) if record.banned_at else None,
            suspended_until=(
                _as_utc(record.suspended_until)
                if status == ModerationStatusEnum.SUSPENDED
                and record.suspended_until
                else None
            ),
            metrics=record.metrics,
            moderation_history=tuple(
                replace(entry, occurred_at=_as_utc(entry.occurred_at))
                for entry in record.history
            ),
        )

    @staticmethod
    def _to_item(row: AdminUserRecord, now: datetime) -> AdminUserItem:
        status = derive_moderation_status(row.banned_at, row.suspended_until, now)
        return AdminUserItem(
            user_id=row.user_id,
            name=row.name,
            moderation_status=status,
            # Only a running suspension has an end date worth showing.
            suspended_until=(
                _as_utc(row.suspended_until)
                if status == ModerationStatusEnum.SUSPENDED and row.suspended_until
                else None
            ),
            event_count=row.event_count,
            report_count=row.report_count,
        )


__all__ = [
    "DEFAULT_ADMIN_USERS_LIMIT",
    "MAX_ADMIN_USERS_LIMIT",
    "MAX_ADMIN_USERS_SEARCH_LENGTH",
    "MIN_ADMIN_USERS_LIMIT",
    "AdminUserNotFoundError",
    "AdminUsersRepository",
    "AdminUsersService",
    "derive_moderation_status",
]