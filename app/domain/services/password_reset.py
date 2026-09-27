import hashlib
import logging
import secrets
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from pwdlib import PasswordHash

from app.domain.entities import PasswordResetRequest, PasswordResetToken

__all__ = [
    "PasswordResetService",
    "PasswordResetTokenRepository",
    "TooManyPasswordResetRequestsError",
]

logger = logging.getLogger(__name__)
password_hash = PasswordHash.recommended()
request_timestamps: dict[str, deque[float]] = {}
request_timestamps_lock = Lock()
request_limit = 3
request_window_seconds = 15 * 60


class PasswordResetTokenRepository(Protocol):
    def get_active_user_id_by_email(self, email: str) -> UUID | None: ...

    def expire_unverified_codes(self, user_id: UUID, expired_at: datetime) -> None: ...

    def create(self, token: PasswordResetToken) -> PasswordResetToken: ...


class TooManyPasswordResetRequestsError(Exception):
    """Raised when an email exceeds the password reset request limit."""


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
