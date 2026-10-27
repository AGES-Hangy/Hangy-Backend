"""Shared bilateral block predicate and transaction lock (no commits)."""

from hashlib import blake2b
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, or_, select, text
from sqlalchemy.orm import Session

from app.infrastructure.repository.models import UserBlockModel

__all__ = ["block_exists_between", "is_blocked_for_write", "lock_user_pair"]


def block_exists_between(
    user_a: UUID | ColumnElement[UUID], user_b: UUID | ColumnElement[UUID]
) -> ColumnElement[bool]:
    """SQL condition for "either user blocked the other".

    Accepts columns too, so list queries can filter rows in the database with
    the same rule BlockService.is_blocked_between applies to a single pair.
    """
    return exists().where(
        or_(
            and_(
                UserBlockModel.blocker_id == user_a,
                UserBlockModel.blocked_id == user_b,
            ),
            and_(
                UserBlockModel.blocker_id == user_b,
                UserBlockModel.blocked_id == user_a,
            ),
        )
    )


def lock_user_pair(db: Session, user_a: UUID, user_b: UUID) -> None:
    """Serialize block effects and pair writes until commit/rollback on Postgres.

    Block cleanup never locks events. Event writers may therefore hold an event
    lock before this pair lock, but must acquire it before participant/connection
    row locks. SQLite's test transactions do not model concurrent production writes.
    """
    if db.get_bind().dialect.name == "postgresql":
        pair = b"".join(value.bytes for value in sorted((user_a, user_b)))
        key = int.from_bytes(blake2b(pair, digest_size=8).digest(), "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def is_blocked_for_write(db: Session, user_a: UUID, user_b: UUID) -> bool:
    lock_user_pair(db, user_a, user_b)
    return bool(db.scalar(select(block_exists_between(user_a, user_b))))
