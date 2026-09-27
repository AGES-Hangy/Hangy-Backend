from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

__all__ = ["PasswordResetRequest", "PasswordResetToken"]


@dataclass(frozen=True, slots=True)
class PasswordResetRequest:
    email: str


@dataclass(frozen=True, slots=True)
class PasswordResetToken:
    token_id: UUID
    user_id: UUID
    code_hash: str
    attempts: int
    verified_at: datetime | None
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime
