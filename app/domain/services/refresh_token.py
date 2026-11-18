"""Rotated refresh tokens.

An access token lives `ACCESS_TOKEN_EXPIRE_MINUTES`; the app trades a refresh
token for a new pair through POST /auth/refresh. Every refresh revokes the
token it used, so each one works once. Reusing a revoked token means it leaked
(or a client retried after losing the answer): the whole family is revoked and
the user signs in again. A refresh is also refused for deleted or moderated
accounts and for tokens issued before the last password change.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.entities import IssuedRefreshToken, RefreshTokenRecord, User
from app.domain.services.auth import (
    AccountDeletedError,
    AccountModeratedError,
    _as_utc,
    _is_moderated,
)

__all__ = [
    "InvalidRefreshTokenError",
    "RefreshTokenRepository",
    "RefreshTokenService",
]

REFRESH_TOKEN_BYTES = 32


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token is unknown, expired, revoked or stale."""


class RefreshTokenRepository(Protocol):
    def add(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        family_id: UUID,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    def get_by_hash_for_update(self, token_hash: str) -> RefreshTokenRecord | None: ...

    def revoke(self, token_id: UUID, revoked_at: datetime) -> None: ...

    def revoke_family(self, family_id: UUID, revoked_at: datetime) -> None: ...

    def get_user(self, user_id: UUID) -> User | None: ...

    def commit(self) -> None: ...


def hash_refresh_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RefreshTokenService:
    def __init__(self, repository: RefreshTokenRepository, expire_days: int) -> None:
        self.repository = repository
        self.lifetime = timedelta(days=expire_days)

    def issue(self, user_id: UUID, family_id: UUID | None = None) -> IssuedRefreshToken:
        value = self._new_token(user_id, family_id or uuid4(), datetime.now(UTC))
        self.repository.commit()
        return value

    def _new_token(
        self, user_id: UUID, family_id: UUID, now: datetime
    ) -> IssuedRefreshToken:
        value = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
        self.repository.add(
            token_id=uuid4(),
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_refresh_token(value),
            created_at=now,
            expires_at=now + self.lifetime,
        )
        return IssuedRefreshToken(
            value=value, expires_in=int(self.lifetime.total_seconds())
        )

    def rotate(self, value: str) -> tuple[User, IssuedRefreshToken]:
        now = datetime.now(UTC)
        record = self.repository.get_by_hash_for_update(hash_refresh_token(value))
        if record is None:
            raise InvalidRefreshTokenError
        if record.revoked_at is not None:
            # Reuse of a spent token: cut the whole chain off.
            self.repository.revoke_family(record.family_id, now)
            self.repository.commit()
            raise InvalidRefreshTokenError
        if _as_utc(record.expires_at) <= now:
            raise InvalidRefreshTokenError

        user = self.repository.get_user(record.user_id)
        if user is None:
            raise InvalidRefreshTokenError
        if user.deleted_at is not None:
            raise AccountDeletedError
        if _is_moderated(user, now):
            raise AccountModeratedError
        if user.password_changed_at is not None and _as_utc(
            record.created_at
        ) < _as_utc(user.password_changed_at):
            raise InvalidRefreshTokenError

        self.repository.revoke(record.token_id, now)
        issued = self._new_token(record.user_id, record.family_id, now)
        self.repository.commit()
        return user, issued

    def revoke(self, value: str) -> None:
        """Log out: end the family of this token. Unknown tokens are ignored."""
        record = self.repository.get_by_hash_for_update(hash_refresh_token(value))
        if record is not None:
            self.repository.revoke_family(record.family_id, datetime.now(UTC))
            self.repository.commit()
