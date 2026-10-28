from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum


@dataclass(frozen=True, slots=True)
class AuditLogEntry:
    audit_log_id: UUID
    actor_id: UUID | None
    actor_name: str | None
    action: AuditActionEnum
    target_type: AuditTargetTypeEnum
    target_id: UUID
    target_label: str | None
    created_at: datetime
