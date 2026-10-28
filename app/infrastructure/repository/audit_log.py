from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import AuditLogEntry
from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum
from app.infrastructure.repository.models import AuditLogModel, TagModel, UserModel


class SqlAlchemyAuditLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        actor_id: UUID,
        action: AuditActionEnum,
        target_type: AuditTargetTypeEnum,
        target_id: UUID,
        target_label: str | None,
        metadata: dict[str, Any] | None,
    ) -> UUID:
        model = AuditLogModel(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            extra_metadata=metadata,
        )
        self.db.add(model)
        self.db.flush()
        return model.audit_log_id

    def resolve(self, target_type: AuditTargetTypeEnum, target_id: UUID) -> str | None:
        if target_type is AuditTargetTypeEnum.USER:
            user = self.db.get(UserModel, target_id)
            return user.name if user is not None and user.name else None
        if target_type is AuditTargetTypeEnum.TAG:
            tag = self.db.get(TagModel, target_id)
            return tag.tag_name if tag is not None else None
        # REPORT rows have no display name, only a UUID: fall back to a short
        # fragment of it so the summary has something stable to reference.
        return f"#{str(target_id)[:8]}"

    def list_entries(
        self,
        *,
        target_type: AuditTargetTypeEnum | None,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
    ) -> list[AuditLogEntry]:
        stmt = (
            select(AuditLogModel)
            .options(joinedload(AuditLogModel.actor))
            .order_by(
                AuditLogModel.created_at.desc(), AuditLogModel.audit_log_id.desc()
            )
            .limit(limit)
        )

        if target_type is not None:
            stmt = stmt.where(AuditLogModel.target_type == target_type)

        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                (AuditLogModel.created_at < cursor_created_at)
                | (
                    (AuditLogModel.created_at == cursor_created_at)
                    & (AuditLogModel.audit_log_id < cursor_id)
                )
            )

        rows = self.db.scalars(stmt).unique().all()
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(model: AuditLogModel) -> AuditLogEntry:
        return AuditLogEntry(
            audit_log_id=model.audit_log_id,
            actor_id=model.actor_id,
            actor_name=model.actor.name if model.actor is not None else None,
            action=model.action,
            target_type=model.target_type,
            target_id=model.target_id,
            target_label=model.target_label,
            created_at=model.created_at,
        )
