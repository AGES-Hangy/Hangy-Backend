from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pwdlib import PasswordHash

from app.domain.entities import User

password_hash = PasswordHash.recommended()


class DeleteAccountRepository(Protocol):
    def get_by_id(self, user_id: UUID) -> User | None: ...

    def soft_delete(self, user_id: UUID, deleted_at: datetime) -> None: ...

    def has_future_events_as_organizer(self, user_id: UUID) -> bool: ...


class PasswordConfirmationError(Exception):
    """Raised when the supplied password does not match the account's hash."""


class HasFutureEventsError(Exception):
    """Raised when the user organizes future events that would be orphaned."""


class DeleteAccountService:
    def __init__(self, repository: DeleteAccountRepository) -> None:
        self.repository = repository

    def delete_account(self, user: User, password: str) -> None:
        if not password_hash.verify(password, user.password_hash):
            raise PasswordConfirmationError

        if self.repository.has_future_events_as_organizer(user.user_id):  # type: ignore[arg-type]
            raise HasFutureEventsError

        now = datetime.now(UTC)
        self.repository.soft_delete(user.user_id, now)  # type: ignore[arg-type]
