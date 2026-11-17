from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

__all__ = ["IssuedRefreshToken", "RefreshTokenRecord"]


@dataclass(frozen=True, slots=True)
class RefreshTokenRecord:
    token_id: UUID
    user_id: UUID
    family_id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    """The opaque value handed to the client once; only its hash is stored."""

    value: str
    expires_in: int
