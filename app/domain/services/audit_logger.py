"""AuditLogger — internal write path called by other services.

Mirrors NotificationDispatcher (app/domain/services/notification_dispatcher.py):
a single place every admin action records through, which must never fail the
caller's own operation. Losing an audit row is bad; blocking a ban because the
audit write failed is worse.
"""

import logging
from typing import Any, Protocol
from uuid import UUID

from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum

logger = logging.getLogger(__name__)

__all__ = ["AuditLogWriteRepository", "AuditLogger", "AuditTargetLabelResolver"]


class AuditLogWriteRepository(Protocol):
    def record(
        self,
        *,
        actor_id: UUID,
        action: AuditActionEnum,
        target_type: AuditTargetTypeEnum,
        target_id: UUID,
        target_label: str | None,
        metadata: dict[str, Any] | None,
    ) -> UUID: ...


class AuditTargetLabelResolver(Protocol):
    def resolve(
        self, target_type: AuditTargetTypeEnum, target_id: UUID
    ) -> str | None: ...


class AuditLogger:
    def __init__(
        self,
        repository: AuditLogWriteRepository,
        label_resolver: AuditTargetLabelResolver,
    ) -> None:
        self.repository = repository
        self.label_resolver = label_resolver

    def record(
        self,
        *,
        actor_id: UUID,
        action: AuditActionEnum,
        target_type: AuditTargetTypeEnum,
        target_id: UUID,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            target_label = self.label_resolver.resolve(target_type, target_id)
            self.repository.record(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                target_label=target_label,
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                "Audit log record failed for action=%s target_type=%s target_id=%s",
                action,
                target_type,
                target_id,
            )
