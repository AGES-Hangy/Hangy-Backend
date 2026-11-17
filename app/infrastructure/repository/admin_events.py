from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.domain.entities import (
    AdminEventDetailRecord,
    AdminEventMetrics,
    AdminEventOrganizerRecord,
)
from app.domain.enums import (
    EventParticipantStatusEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
)
from app.infrastructure.repository.admin_users import SqlAlchemyAdminUsersRepository
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserModel,
)
from app.infrastructure.repository.models.report_model import ReportModel

__all__ = ["SqlAlchemyAdminEventsRepository"]


class SqlAlchemyAdminEventsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_detail(self, event_id: UUID) -> AdminEventDetailRecord | None:
        """The moderation file of an event.

        Unlike the public lookups this does not filter `deleted_at`: a removed
        event keeps its file so the admin can still read its reports.
        """
        model = self.db.scalar(
            select(EventModel)
            .options(selectinload(EventModel.tags))
            .where(EventModel.event_id == event_id)
        )
        if model is None:
            return None
        organizer = self.db.scalar(
            select(UserModel).where(UserModel.user_id == model.event_creator_id)
        )
        if organizer is None:
            return None

        return AdminEventDetailRecord(
            event_id=model.event_id,
            title=model.event_title,
            description=model.event_description,
            starts_at=model.starts_at,
            ends_at=model.ends_at,
            location_name=model.location_name,
            location_neighborhood=model.location_neighborhood,
            location_city=model.location_city,
            latitude=model.event_latitude,
            longitude=model.event_longitude,
            privacy=model.event_privacy,
            status=model.event_status,
            moderation_status=model.moderation_status,
            removed_at=model.removed_at,
            cover_photo_url=model.cover_photo_url,
            max_participants=model.max_participants,
            created_at=model.created_at,
            tags=tuple(sorted(tag.tag_name for tag in model.tags)),
            organizer=self._organizer(organizer),
            metrics=self._metrics(event_id),
        )

    def _organizer(self, user: UserModel) -> AdminEventOrganizerRecord:
        users = SqlAlchemyAdminUsersRepository(self.db)
        metrics = users.metrics_for(user.user_id)
        return AdminEventOrganizerRecord(
            user_id=user.user_id,
            name=user.name,
            photo_url=user.profile_photo_url,
            banned_at=user.banned_at,
            suspended_until=user.suspended_until,
            event_count=metrics.event_count,
            report_count=metrics.report_count,
        )

    def _metrics(self, event_id: UUID) -> AdminEventMetrics:
        participant_count, pending_count = self.db.execute(
            select(
                func.count().filter(
                    EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED
                ),
                func.count().filter(
                    EventParticipantModel.status == EventParticipantStatusEnum.PENDING
                ),
            ).where(EventParticipantModel.event_id == event_id)
        ).one()
        # Same rule as the user file: archived reports (REJECTED) do not count,
        # and a report is upheld when it ended with the event removed.
        report_count, report_upheld_count = self.db.execute(
            select(
                func.count(),
                func.count().filter(
                    ReportModel.resolution_action
                    == ReportResolutionActionEnum.EVENT_REMOVED
                ),
            ).where(
                ReportModel.reported_event_id == event_id,
                ReportModel.deleted_at.is_(None),
                ReportModel.status != ReportStatusEnum.REJECTED,
            )
        ).one()
        return AdminEventMetrics(
            participant_count=participant_count,
            pending_count=pending_count,
            report_count=report_count,
            report_upheld_count=report_upheld_count,
        )
