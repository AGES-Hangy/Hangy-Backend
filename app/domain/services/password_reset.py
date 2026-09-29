import hashlib
import logging
import secrets
import time
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from pwdlib import PasswordHash

from app.domain.entities import (
    PasswordResetRequest,
    PasswordResetToken,
    VerifyResetCode,
)

__all__ = [
    "InvalidResetCodeError",
    "PasswordResetService",
    "PasswordResetTokenRepository",
    "TooManyPasswordResetRequestsError",
    "TooManyResetCodeAttemptsError",
]

logger = logging.getLogger(__name__)
password_hash = PasswordHash.recommended()
request_timestamps: dict[str, deque[float]] = {}
request_timestamps_lock = Lock()
request_limit = 3
request_window_seconds = 15 * 60
max_code_attempts = 5


class PasswordResetTokenRepository(Protocol):
    def get_active_user_id_by_email(self, email: str) -> UUID | None: ...

    def expire_unverified_codes(self, user_id: UUID, expired_at: datetime) -> None: ...

    def create(self, token: PasswordResetToken) -> PasswordResetToken: ...

    def get_latest_by_email(self, email: str) -> PasswordResetToken | None: ...

    def increment_attempts(self, token_id: UUID) -> None: ...

    def mark_verified(self, token_id: UUID, verified_at: datetime) -> None: ...


class TooManyPasswordResetRequestsError(Exception):
    """Raised when an email exceeds the password reset request limit."""


class InvalidResetCodeError(Exception):
    """Raised when the code is wrong, expired, used or has no pending token."""


class TooManyResetCodeAttemptsError(Exception):
    """Raised when a token exceeded the wrong-code attempt limit."""


class PasswordResetService:
    def __init__(self, repository: PasswordResetTokenRepository) -> None:
        self.repository = repository

    def request_password_reset(self, request: PasswordResetRequest) -> None:
        _enforce_request_limit(request.email)
        user_id = self.repository.get_active_user_id_by_email(request.email)
        if user_id is None:
            return

        now = datetime.now(UTC)
        code = f"{secrets.randbelow(1_000_000):06d}"
        token = PasswordResetToken(
            token_id=uuid4(),
            user_id=user_id,
            code_hash=password_hash.hash(code),
            attempts=0,
            verified_at=None,
            expires_at=now + timedelta(minutes=15),
            used_at=None,
            created_at=now,
        )
        self.repository.expire_unverified_codes(user_id, now)
        self.repository.create(token)
        logger.info("Password reset code: %s", code)

    def verify_code(self, verification: VerifyResetCode) -> PasswordResetToken:
        token = self.repository.get_latest_by_email(verification.email)
        now = datetime.now(UTC)
        if (
            token is None
            or token.used_at is not None
            or _as_utc(token.expires_at) <= now
        ):
            raise InvalidResetCodeError
        if token.attempts >= max_code_attempts:
            raise TooManyResetCodeAttemptsError
        if not password_hash.verify(verification.code, token.code_hash):
            self.repository.increment_attempts(token.token_id)
            raise InvalidResetCodeError

        self.repository.mark_verified(token.token_id, now)
        return replace(token, verified_at=now)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _enforce_request_limit(email: str) -> None:
    now = time.monotonic()
    key = hashlib.sha256(email.casefold().encode()).hexdigest()
    with request_timestamps_lock:
        timestamps = request_timestamps.setdefault(key, deque())
        while timestamps and now - timestamps[0] >= request_window_seconds:
            timestamps.popleft()
        if len(timestamps) >= request_limit:
            raise TooManyPasswordResetRequestsError
        timestamps.append(now)
