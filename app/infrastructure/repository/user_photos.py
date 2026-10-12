from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.entities import UserPhoto
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)


class SqlAlchemyUserPhotosRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_photo_id: UUID | None,
    ) -> list[UserPhoto]:
        """List the photos the user published, newest first.

        The filters mirror the `photos` counter of `get_profile_counts`, so the
        list never disagrees with the number shown on the Photos tab.
        """
        stmt = (
            select(ExperienceImagesModel, EventModel.event_id, EventModel.event_title)
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
            .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
            .where(
                EventParticipantModel.user_id == user_id,
                EventExperienceModel.deleted_at.is_(None),
                ExperienceImagesModel.deleted_at.is_(None),
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
            UserPhoto(
                photo_id=image.photo_id,
                photo_url=image.photo_url,
                event_id=event_id,
                event_title=event_title,
                created_at=image.created_at,
            )
            for image, event_id, event_title in rows
        ]