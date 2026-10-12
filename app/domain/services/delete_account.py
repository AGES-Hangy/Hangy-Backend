from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import User
from app.domain.services.auth import password_hash


class DeleteAccountRepository(Protocol):
    def soft_delete(self, user_id: UUID, deleted_at: datetime) -> None: ...

    def has_future_events_as_organizer(self, user_id: UUID, now: datetime) -> bool: ...


class PasswordConfirmationError(Exception):
    """Raised when the supplied password does not match the account's hash."""


class HasFutureEventsError(Exception):
    """Raised when the user organizes future events that would be orphaned."""


class DeleteAccountService:
    def __init__(self, repository: DeleteAccountRepository) -> None:
        self.repository = repository

    def delete_account(self, user: User, password: str) -> None:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")

        if not password_hash.verify(password, user.password_hash):
            raise PasswordConfirmationError

        now = datetime.now(UTC)

        if self.repository.has_future_events_as_organizer(user.user_id, now):
            raise HasFutureEventsError

        self.repository.soft_delete(user.user_id, now)
