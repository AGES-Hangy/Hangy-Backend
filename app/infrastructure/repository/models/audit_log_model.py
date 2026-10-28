from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.user_model import UserModel


class AuditLogModel(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        # Serves the newest-first listing.
        Index("ix_audit_log_created_at", text("created_at DESC")),
        Index("ix_audit_log_target_type", "target_type"),
    )

    audit_log_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    # Nullable + ON DELETE SET NULL: the row must survive the admin account
    # being hard-deleted later.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    action: Mapped[AuditActionEnum] = mapped_column(enum_column(AuditActionEnum))
    # No FK: the target is polymorphic across user/report/tag.
    target_type: Mapped[AuditTargetTypeEnum] = mapped_column(
        enum_column(AuditTargetTypeEnum)
    )
    target_id: Mapped[uuid.UUID]
    # Snapshot of the target's display name taken at write time, so the
    # summary stays correct even if the target is later renamed or deleted.
    target_label: Mapped[str | None] = mapped_column(String(255))
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    actor: Mapped[UserModel | None] = relationship()
