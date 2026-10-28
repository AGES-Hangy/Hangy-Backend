__all__ = [
    "AuditLogActorOutput",
    "AuditLogItemOutput",
    "AuditLogPaginatedResponse",
]

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum


class AuditLogActorOutput(BaseModel):
    id: UUID | None
    name: str


class AuditLogItemOutput(BaseModel):
    audit_log_id: UUID
    actor: AuditLogActorOutput
    action: AuditActionEnum
    target_type: AuditTargetTypeEnum
    target_id: UUID
    summary: str
    created_at: datetime


class AuditLogPaginatedResponse(BaseModel):
    items: list[AuditLogItemOutput]
    next_cursor: str | None
