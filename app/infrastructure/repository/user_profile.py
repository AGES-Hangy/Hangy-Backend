from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.domain.entities import (
    BusinessProfile,
    EditedPersonProfile,
    PersonProfile,
    UserProfileCounts,
)
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    UserConnectionStatusEnum,
)
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    EventModel,
    EventParticipantModel,
    PersonProfileModel,
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
        # A FINISHED event is over even if it was closed before ends_at; a
        # PUBLISHED one is over once ends_at is reached. CANCELLED and DRAFT
        # events belong to neither tab.
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
        # Name and bio are shared by every user type, so they live on user;
        # the location belongs to person_profile. Both change in one commit.
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
