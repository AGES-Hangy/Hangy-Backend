from sqlalchemy.orm import Session

from app.domain.entities import AuditEvent
from app.infrastructure.repository.models import AuditLogModel


class SqlAlchemyAuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, event: AuditEvent) -> None:
        """Store the event and commit the open transaction.

        Committing here makes the audited change and its audit row atomic: if
        this fails, both are rolled back.
        """
        self.db.add(
            AuditLogModel(
                action=event.action,
                actor_id=event.actor_id,
                target_id=event.target_id,
                created_at=event.created_at,
                extra_metadata=event.metadata,
            )
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
