from uuid import UUID

from app.domain.entities import AuditLogEntry
from app.domain.enums import AuditActionEnum
from app.presentation.dtos.audit_log import (
    AuditLogActorOutput,
    AuditLogItemOutput,
    AuditLogPaginatedResponse,
)

__all__ = ["AuditLogAssembler"]


def _actor_display_name(entry: AuditLogEntry, current_admin_id: UUID) -> str:
    if entry.actor_id == current_admin_id:
        return "Você"
    return entry.actor_name or "Administrador removido"


def _summary(entry: AuditLogEntry, actor_name: str) -> str:
    label = entry.target_label or ""
    if entry.action is AuditActionEnum.USER_BANNED:
        return f"{actor_name} baniu {label or 'um usuário'}"
    if entry.action is AuditActionEnum.USER_SUSPENDED:
        return f"{actor_name} suspendeu {label or 'um usuário'}"
    if entry.action is AuditActionEnum.USER_REVERTED:
        return f"{actor_name} reverteu a ação sobre {label or 'um usuário'}"
    if entry.action is AuditActionEnum.REPORT_ARCHIVED:
        return f"{actor_name} arquivou a denúncia {label}".rstrip()
    if entry.action is AuditActionEnum.TAG_CREATED:
        return f"{actor_name} criou a tag {label}".rstrip()
    if entry.action is AuditActionEnum.TAG_UPDATED:
        return f"{actor_name} editou a tag {label}".rstrip()
    if entry.action is AuditActionEnum.TAG_DELETED:
        return f"{actor_name} removeu a tag {label}".rstrip()
    raise AssertionError(f"Unhandled audit action: {entry.action}")


class AuditLogAssembler:
    @staticmethod
    def to_paginated_response(
        entries: list[AuditLogEntry],
        next_cursor: str | None,
        current_admin_id: UUID,
    ) -> AuditLogPaginatedResponse:
        return AuditLogPaginatedResponse(
            items=[
                AuditLogAssembler._to_item(entry, current_admin_id) for entry in entries
            ],
            next_cursor=next_cursor,
        )

    @staticmethod
    def _to_item(entry: AuditLogEntry, current_admin_id: UUID) -> AuditLogItemOutput:
        actor_name = _actor_display_name(entry, current_admin_id)
        return AuditLogItemOutput(
            audit_log_id=entry.audit_log_id,
            actor=AuditLogActorOutput(id=entry.actor_id, name=actor_name),
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            summary=_summary(entry, actor_name),
            created_at=entry.created_at,
        )
