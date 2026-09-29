from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

__all__ = [
    "PasswordResetRequest",
    "PasswordResetToken",
    "ResetToken",
    "VerifyResetCode",
]


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


@dataclass(frozen=True, slots=True)
class VerifyResetCode:
    email: str
    code: str


@dataclass(frozen=True, slots=True)
class ResetToken:
    value: str
    expires_in: int
