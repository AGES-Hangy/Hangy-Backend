from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import (
    BusinessProfile,
    EditedPersonProfile,
    PersonProfile,
    UserProfileCounts,
)
from app.domain.entities.tag import Tag
from app.domain.entities.user_profile import UserProfileData
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    UserConnectionStatusEnum,
    UserTypeEnum,
)
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    EventModel,
    EventParticipantModel,
    PersonProfileModel,
    UserConnectionModel,
    UserModel,
    user_follows,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)
from app.infrastructure.repository.models.user_block_model import (
    UserBlockModel,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyUserProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_person_profile(self, user_id: UUID) -> PersonProfile | None:
        model = self.db.get(PersonProfileModel, user_id)
        return self._to_person_entity(model) if model is not None else None

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None:
        model = self.db.get(BusinessProfileModel, user_id)
        return self._to_business_entity(model) if model is not None else None

    def get_profile_counts(self, user_id: UUID) -> UserProfileCounts:
        """Every counter of the profile screen, aggregated in a single query."""
        now = _now_utc()

        is_over = or_(
            EventModel.event_status == EventStatusEnum.FINISHED,
            EventModel.ends_at <= now,
        )

        def confirmed_participations(*conditions):
            return (
                select(func.count())
                .select_from(EventParticipantModel)
                .join(EventModel, EventModel.event_id == EventParticipantModel.event_id)
                .where(
                    EventParticipantModel.user_id == user_id,
                    EventParticipantModel.status
                    == EventParticipantStatusEnum.CONFIRMED,
                    EventModel.deleted_at.is_(None),
                    *conditions,
                )
                .scalar_subquery()
            )

        confirmed = confirmed_participations(
            EventModel.event_status == EventStatusEnum.PUBLISHED, ~is_over
        )
        past = confirmed_participations(
            EventModel.event_status.in_(
                (EventStatusEnum.PUBLISHED, EventStatusEnum.FINISHED)
            ),
            is_over,
        )
        photos = (
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
                EventExperienceModel.deleted_at.is_(None),
                ExperienceImagesModel.deleted_at.is_(None),
            )
            .scalar_subquery()
        )
        connections = (
            select(func.count())
            .select_from(UserConnectionModel)
            .where(
                or_(
                    UserConnectionModel.requester_id == user_id,
                    UserConnectionModel.receiver_id == user_id,
                ),
                UserConnectionModel.status == UserConnectionStatusEnum.CONFIRMED,
                UserConnectionModel.deleted_at.is_(None),
            )
            .scalar_subquery()
        )

        row = self.db.execute(select(past, confirmed, photos, connections)).one()
        return UserProfileCounts(
            past=row[0], confirmed=row[1], photos=row[2], connections=row[3]
        )

    def update_person_profile(
        self, profile: EditedPersonProfile
    ) -> EditedPersonProfile:
        self.db.execute(
            update(UserModel)
            .where(
                UserModel.user_id == profile.user_id,
                UserModel.deleted_at.is_(None),
            )
            .values(
                name=profile.name,
                description=profile.description,
                updated_at=profile.updated_at,
            )
        )
        self.db.execute(
            update(PersonProfileModel)
            .where(
                PersonProfileModel.user_id == profile.user_id,
                PersonProfileModel.user.has(UserModel.deleted_at.is_(None)),
            )
            .values(
                state=profile.state,
                city=profile.city,
                updated_at=profile.updated_at,
            )
        )
        self.db.commit()
        return profile

    @staticmethod
    def _to_person_entity(model: PersonProfileModel) -> PersonProfile:
        return PersonProfile(
            user_id=model.user_id,
            cpf=model.cpf,
            date_of_birth=model.date_of_birth,
            state=model.state,
            city=model.city,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_business_entity(model: BusinessProfileModel) -> BusinessProfile:
        return BusinessProfile(
            user_id=model.user_id,
            cnpj=model.cnpj,
            address=model.address,
            updated_at=model.updated_at,
            business_latitude=model.business_latitude,
            business_longitude=model.business_longitude,
        )

    def get_profile(self, user_id: UUID, viewer_id: UUID) -> UserProfileData | None:
        model = (
            self.db.execute(
                select(UserModel)
                .where(
                    UserModel.user_id == user_id,
                    UserModel.deleted_at.is_(None),
                )
                .options(joinedload(UserModel.tags))
            )
            .unique()
            .scalar_one_or_none()
        )

        if model is None:
            return None

        if self._viewer_is_blocked(user_id=user_id, viewer_id=viewer_id):
            return None

        connections_count = 0
        is_following = False
        connection_status = None

        if model.user_type == UserTypeEnum.PERSONAL:
            connections_count = (
                self.db.scalar(
                    select(func.count(UserConnectionModel.connection_id)).where(
                        UserConnectionModel.status
                        == UserConnectionStatusEnum.CONFIRMED,
                        or_(
                            UserConnectionModel.requester_id == user_id,
                            UserConnectionModel.receiver_id == user_id,
                        ),
                    )
                )
                or 0
            )

            if viewer_id != user_id:
                connection_status = self.db.scalar(
                    select(UserConnectionModel.status).where(
                        or_(
                            and_(
                                UserConnectionModel.requester_id == viewer_id,
                                UserConnectionModel.receiver_id == user_id,
                            ),
                            and_(
                                UserConnectionModel.requester_id == user_id,
                                UserConnectionModel.receiver_id == viewer_id,
                            ),
                        )
                    )
                )
        else:
            connections_count = (
                self.db.scalar(
                    select(func.count())
                    .select_from(user_follows)
                    .where(user_follows.c.followed_business_id == user_id)
                )
                or 0
            )

            if viewer_id != user_id:
                is_following = (
                    self.db.scalar(
                        select(func.count())
                        .select_from(user_follows)
                        .where(
                            user_follows.c.follower_id == viewer_id,
                            user_follows.c.followed_business_id == user_id,
                        )
                    )
                    > 0
                )

        return UserProfileData(
            user_id=model.user_id,
            user_type=model.user_type,
            name=model.name,
            description=model.description,
            photo_url=model.profile_photo_url,
            tags=tuple(
                Tag(
                    tag_id=tag.tag_id,
                    tag_name=tag.tag_name,
                    tag_parent_id=tag.tag_parent_id,
                )
                for tag in sorted(
                    model.tags,
                    key=lambda tag: (
                        tag.tag_parent_id is not None,
                        tag.tag_name,
                        tag.tag_id,
                    ),
                )
            ),
            connection_status=connection_status,
            is_following=is_following,
            connections_count=connections_count,
        )

    def _viewer_is_blocked(self, user_id: UUID, viewer_id: UUID) -> bool:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(UserBlockModel)
                .where(
                    UserBlockModel.blocker_id == user_id,
                    UserBlockModel.blocked_id == viewer_id,
                )
            )
            > 0
        )


__all__ = ["SqlAlchemyUserProfileRepository"]
