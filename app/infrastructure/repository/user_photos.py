from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.domain.entities import UserPhoto
from app.domain.enums import EventPrivacyEnum, UserConnectionStatusEnum
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserConnectionModel,
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
        public_only: bool = False,
        by_organizer: bool = False,
    ) -> list[UserPhoto]:
        """List the photos the user published, newest first.

        The filters mirror the `photos` counters of the profile repository, so
        the list never disagrees with the number shown on the Photos tab. A
        visitor (`public_only`) only sees the photos of PUBLIC events. With
        `by_organizer`, the photos anyone published on the events `user_id`
        organized (a business gallery).
        """
        stmt = (
            select(
                ExperienceImagesModel,
                EventModel.event_id,
                EventModel.event_title,
                EventExperienceModel.description,
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
            .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
            .where(
                EventModel.event_creator_id == user_id
                if by_organizer
                else EventParticipantModel.user_id == user_id,
                EventExperienceModel.deleted_at.is_(None),
                ExperienceImagesModel.deleted_at.is_(None),
            )
            .order_by(
                ExperienceImagesModel.created_at.desc(),
                ExperienceImagesModel.photo_id.desc(),
            )
        )

        if public_only:
            stmt = stmt.where(
                EventModel.deleted_at.is_(None),
                EventModel.event_privacy == EventPrivacyEnum.PUBLIC,
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
                description=description,
                experience_id=image.experience_id,
            )
            for image, event_id, event_title, description in rows
        ]

    def are_connected(self, user_id: UUID, other_id: UUID) -> bool:
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        UserConnectionModel.status
                        == UserConnectionStatusEnum.CONFIRMED,
                        UserConnectionModel.deleted_at.is_(None),
                        or_(
                            and_(
                                UserConnectionModel.requester_id == user_id,
                                UserConnectionModel.receiver_id == other_id,
                            ),
                            and_(
                                UserConnectionModel.requester_id == other_id,
                                UserConnectionModel.receiver_id == user_id,
                            ),
                        ),
                    )
                )
            )
        )
