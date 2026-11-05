__all__ = ["AuditEvent"]

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import AuditActionEnum


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Who did what, to which record, and when."""

    action: AuditActionEnum
    actor_id: UUID
    target_id: UUID | None
    created_at: datetime
    metadata: dict[str, Any] | None = None
