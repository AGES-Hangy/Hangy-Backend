from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import AuditActionEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class AuditLogModel(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_action_created_at", "action", "created_at"),)

    audit_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action: Mapped[AuditActionEnum] = mapped_column(enum_column(AuditActionEnum))
    # Kept (as NULL) when the account is hard-deleted: the history must survive.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    # No foreign key: the audited record may be deleted later and the row stays.
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
