from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.repository.models import NotificationModel


class SqlAlchemyNotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def count_unread(self, user_id: UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(NotificationModel)
                .where(
                    NotificationModel.user_id == user_id,
                    NotificationModel.read.is_(False),
                )
            )
            or 0
        )
