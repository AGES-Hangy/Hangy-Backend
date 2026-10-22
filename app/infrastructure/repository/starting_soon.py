from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.domain.entities import StartingSoonCandidate
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
    UserModel,
)


class SqlAlchemyStartingSoonRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_unnotified_candidates(
        self, starts_after: datetime, starts_until: datetime
    ) -> list[StartingSoonCandidate]:
        already_notified = exists().where(
            EventParticipantNotificationModel.participant_id
            == EventParticipantModel.participant_id,
            NotificationModel.notification_id
            == EventParticipantNotificationModel.notification_id,
            NotificationModel.type == NotificationTypeEnum.EVENT_STARTING_SOON,
        )
        rows = self.db.execute(
            select(
                EventParticipantModel.participant_id,
                EventParticipantModel.user_id,
                EventParticipantModel.event_id,
            )
            .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
            .join(UserModel, UserModel.user_id == EventParticipantModel.user_id)
            .where(
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
                EventModel.event_status == EventStatusEnum.PUBLISHED,
                EventModel.deleted_at.is_(None),
                UserModel.deleted_at.is_(None),
                EventModel.starts_at > starts_after,
                EventModel.starts_at <= starts_until,
                ~already_notified,
            )
            .order_by(EventModel.starts_at, EventParticipantModel.participant_id)
        ).all()
        return [
            StartingSoonCandidate(
                participant_id=row.participant_id,
                user_id=row.user_id,
                event_id=row.event_id,
            )
            for row in rows
        ]

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
