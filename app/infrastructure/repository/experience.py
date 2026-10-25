from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import (
    EventExperience,
    EventExperienceAccess,
    EventPhoto,
    ExperiencePhotoAccess,
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
    ExperienceImagesModel,
    UserModel,
)

__all__ = ["SqlAlchemyExperienceRepository"]


class SqlAlchemyExperienceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_access(self, event_id: UUID, user_id: UUID) -> EventExperienceAccess | None:
        return self._load_access(event_id, user_id, lock=False)

    def get_access_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventExperienceAccess | None:
        return self._load_access(event_id, user_id, lock=True)

    def _load_access(
        self, event_id: UUID, user_id: UUID, *, lock: bool
    ) -> EventExperienceAccess | None:
        stmt = (
            select(EventModel, EventParticipantModel)
            .outerjoin(
                EventParticipantModel,
                and_(
                    EventParticipantModel.event_id == EventModel.event_id,
                    EventParticipantModel.user_id == user_id,
                ),
            )
            .where(EventModel.event_id == event_id, EventModel.deleted_at.is_(None))
        )
        if lock:
            stmt = stmt.with_for_update(of=EventModel).execution_options(
                populate_existing=True
            )
        row = self.db.execute(stmt).one_or_none()
        if row is None:
            return None

        event_model, participant_model = row
        return EventExperienceAccess(
            event=SqlAlchemyEventRepository.to_entity(event_model),
            participant=(
                SqlAlchemyEventRepository.to_participant_entity(participant_model)
                if participant_model is not None
                else None
            ),
            organizer_blocked_viewer=SqlAlchemyEventDetailsRepository(
                self.db
            ).organizer_blocked_viewer(event_model.event_creator_id, user_id),
        )

    def list_event_photos(
        self,
        event_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_photo_id: UUID | None,
    ) -> list[EventPhoto]:
        stmt = (
            select(ExperienceImagesModel, UserModel.user_id, UserModel.name)
            .join(
                EventExperienceModel,
                EventExperienceModel.experience_id
                == ExperienceImagesModel.experience_id,
            )
            .join(
                EventParticipantModel,
                EventParticipantModel.participant_id
                == EventExperienceModel.event_participant_id,
            )
            .join(UserModel, UserModel.user_id == EventParticipantModel.user_id)
            .where(
                EventParticipantModel.event_id == event_id,
                EventExperienceModel.deleted_at.is_(None),
                ExperienceImagesModel.deleted_at.is_(None),
                UserModel.deleted_at.is_(None),
            )
            .order_by(
                ExperienceImagesModel.created_at.desc(),
                ExperienceImagesModel.photo_id.desc(),
            )
        )
        if cursor_created_at is not None and cursor_photo_id is not None:
            stmt = stmt.where(
                or_(
                    ExperienceImagesModel.created_at < cursor_created_at,
                    (ExperienceImagesModel.created_at == cursor_created_at)
                    & (ExperienceImagesModel.photo_id < cursor_photo_id),
                )
            )
        rows = self.db.execute(stmt.limit(limit)).all()
        return [
            EventPhoto(
                photo_id=image.photo_id,
                photo_url=image.photo_url,
                author_id=author_id,
                author_name=author_name,
                created_at=image.created_at,
            )
            for image, author_id, author_name in rows
        ]

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

    def get_photo_access(self, photo_id: UUID) -> ExperiencePhotoAccess | None:
        stmt = (
            select(
                ExperienceImagesModel.photo_id,
                ExperienceImagesModel.photo_url,
                UserModel.user_id,
                EventModel.event_creator_id,
            )
            .join(
                EventExperienceModel,
                EventExperienceModel.experience_id
                == ExperienceImagesModel.experience_id,
            )
            .join(
                EventParticipantModel,
                EventParticipantModel.participant_id
                == EventExperienceModel.event_participant_id,
            )
            .join(UserModel, UserModel.user_id == EventParticipantModel.user_id)
            .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
            .where(
                ExperienceImagesModel.photo_id == photo_id,
                ExperienceImagesModel.deleted_at.is_(None),
                EventExperienceModel.deleted_at.is_(None),
                UserModel.deleted_at.is_(None),
                EventModel.deleted_at.is_(None),
            )
        )
        row = self.db.execute(stmt).one_or_none()
        if row is None:
            return None
        return ExperiencePhotoAccess(
            photo_id=row.photo_id,
            photo_url=row.photo_url,
            author_id=row.user_id,
            organizer_id=row.event_creator_id,
        )

    def soft_delete_photo(self, photo_id: UUID) -> bool:
        result = self.db.execute(
            update(ExperienceImagesModel)
            .where(
                ExperienceImagesModel.photo_id == photo_id,
                ExperienceImagesModel.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        )
        self.db.commit()
        return result.rowcount == 1

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
