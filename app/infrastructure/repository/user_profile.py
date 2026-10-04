from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.domain.entities.tag import Tag
from app.domain.entities.user_profile import UserProfile, UserProfileCounts
from app.domain.enums import EventParticipantStatusEnum, UserConnectionStatusEnum
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)
from app.infrastructure.repository.models.user_connection_model import (
    UserConnectionModel,
)

_CONFIRMED = EventParticipantStatusEnum.CONFIRMED
_CONNECTION_CONFIRMED = UserConnectionStatusEnum.CONFIRMED


def _now_utc() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyUserProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_profile(self, user_id: UUID) -> UserProfile | None:
        user = self.db.scalar(
            select(UserModel)
            .options(selectinload(UserModel.tags))
            .where(
                UserModel.user_id == user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        if user is None:
            return None

        now = _now_utc()

        confirmed_count = (
            self.db.scalar(
                select(func.count())
                .select_from(EventParticipantModel)
                .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
                .where(
                    EventParticipantModel.user_id == user_id,
                    EventParticipantModel.status == _CONFIRMED,
                    EventModel.ends_at > now,
                    EventModel.deleted_at.is_(None),
                )
            )
            or 0
        )

        past_count = (
            self.db.scalar(
                select(func.count())
                .select_from(EventParticipantModel)
                .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
                .where(
                    EventParticipantModel.user_id == user_id,
                    EventParticipantModel.status == _CONFIRMED,
                    EventModel.ends_at <= now,
                    EventModel.deleted_at.is_(None),
                )
            )
            or 0
        )

        photos_count = (
            self.db.scalar(
                select(func.count())
                .select_from(ExperienceImagesModel)
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
                .where(
                    EventParticipantModel.user_id == user_id,
                    ExperienceImagesModel.deleted_at.is_(None),
                    EventExperienceModel.deleted_at.is_(None),
                )
            )
            or 0
        )

        connections_count = (
            self.db.scalar(
                select(func.count())
                .select_from(UserConnectionModel)
                .where(
                    (
                        (UserConnectionModel.requester_id == user_id)
                        | (UserConnectionModel.receiver_id == user_id)
                    ),
                    UserConnectionModel.status == _CONNECTION_CONFIRMED,
                    UserConnectionModel.deleted_at.is_(None),
                )
            )
            or 0
        )

        return UserProfile(
            user_id=user.user_id,
            name=user.name,
            description=user.description,
            photo_url=user.profile_photo_url,
            tags=tuple(_to_tag_entity(t) for t in user.tags),
            connections_count=connections_count,
            counts=UserProfileCounts(
                past=past_count,
                confirmed=confirmed_count,
                photos=photos_count,
            ),
        )


def _to_tag_entity(model: TagModel) -> Tag:
    return Tag(
        tag_id=model.tag_id,
        tag_name=model.tag_name,
        tag_parent_id=model.tag_parent_id,
    )
