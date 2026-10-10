from datetime import UTC
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import (
    EventExperience,
    EventExperienceAccess,
    NewEventExperience,
)
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.event_details import (
    SqlAlchemyEventDetailsRepository,
)
from app.infrastructure.repository.models import (
    EventExperienceModel,
    EventModel,
    EventParticipantModel,
)

__all__ = ["SqlAlchemyExperienceRepository"]


class SqlAlchemyExperienceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_access_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventExperienceAccess | None:
        row = self.db.execute(
            select(EventModel, EventParticipantModel)
            .outerjoin(
                EventParticipantModel,
                and_(
                    EventParticipantModel.event_id == EventModel.event_id,
                    EventParticipantModel.user_id == user_id,
                ),
            )
            .where(EventModel.event_id == event_id, EventModel.deleted_at.is_(None))
            .with_for_update(of=EventModel)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            return None

        event_model, participant_model = row
        return EventExperienceAccess(
            event=SqlAlchemyEventRepository._to_entity(event_model),
            participant=(
                SqlAlchemyEventRepository._to_participant_entity(participant_model)
                if participant_model is not None
                else None
            ),
            organizer_blocked_viewer=SqlAlchemyEventDetailsRepository(
                self.db
            )._organizer_blocked_viewer(event_model.event_creator_id, user_id),
        )

    def add(
        self, participant_id: UUID, experience: NewEventExperience
    ) -> EventExperience | None:
        model = EventExperienceModel(
            event_participant_id=participant_id,
            description=experience.description,
        )
        self.db.add(model)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            constraint_name = getattr(
                getattr(error.orig, "diag", None), "constraint_name", None
            )
            sqlite_duplicate = (
                "UNIQUE constraint failed: event_experience.event_participant_id"
                in str(error.orig)
            )
            if constraint_name == "uq_event_experience_participant" or sqlite_duplicate:
                return None
            raise
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: EventExperienceModel) -> EventExperience:
        return EventExperience(
            experience_id=model.experience_id,
            event_participant_id=model.event_participant_id,
            description=model.description,
            created_at=(
                model.created_at
                if model.created_at.tzinfo is not None
                else model.created_at.replace(tzinfo=UTC)
            ),
            deleted_at=model.deleted_at,
        )
