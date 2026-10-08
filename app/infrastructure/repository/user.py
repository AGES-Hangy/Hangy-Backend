import secrets
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.enums import EventParticipantStatusEnum, EventStatusEnum
from app.domain.services.auth import password_hash
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.business_profile_model import (
    BusinessProfileModel,
)
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.event_participant_model import (
    EventParticipantModel,
)
from app.infrastructure.repository.models.follow import UserFollowModel
from app.infrastructure.repository.models.person_profile_model import PersonProfileModel
from app.infrastructure.repository.models.user_connection_model import (
    UserConnectionModel,
)
from app.infrastructure.repository.models.user_device_model import UserDeviceModel


class SqlAlchemyUserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: UUID) -> User | None:
        # Deleted accounts are included here too: the auth flow needs to see
        # them to tell "no such account" apart from "this account was deleted".
        model = self.db.scalar(select(UserModel).where(UserModel.user_id == user_id))
        return self._to_entity(model) if model is not None else None

    def get_by_email(self, email: str) -> User | None:
        model = self.db.scalar(select(UserModel).where(UserModel.email == email))
        return self._to_entity(model) if model is not None else None

    def has_future_events_as_organizer(self, user_id: UUID, now: datetime) -> bool:
        stmt = select(EventModel.event_id).where(
            EventModel.event_creator_id == user_id,
            EventModel.deleted_at.is_(None),
            EventModel.event_status == EventStatusEnum.PUBLISHED,
            EventModel.ends_at > now,
        )
        return self.db.scalar(stmt) is not None

    def soft_delete(self, user_id: UUID, deleted_at: datetime) -> None:
        model = self.db.scalar(select(UserModel).where(UserModel.user_id == user_id))
        if model is None:
            return

        model.email = f"deleted_{user_id}@deleted.invalid"
        model.password_hash = password_hash.hash(secrets.token_urlsafe(32))
        model.name = None
        model.description = None
        model.user_phone = None
        model.profile_photo_url = None
        model.deleted_at = deleted_at

        uid_str = str(user_id).replace("-", "")

        self.db.execute(
            update(PersonProfileModel)
            .where(PersonProfileModel.user_id == user_id)
            .values(cpf=uid_str[:11], date_of_birth=date(1900, 1, 1), state="", city="")
        )
        self.db.execute(
            update(BusinessProfileModel)
            .where(BusinessProfileModel.user_id == user_id)
            .values(
                cnpj=uid_str[:14],
                address="",
                business_latitude=None,
                business_longitude=None,
            )
        )
        self.db.execute(
            delete(UserDeviceModel).where(UserDeviceModel.user_id == user_id)
        )
        self.db.execute(
            update(UserConnectionModel)
            .where(
                or_(
                    UserConnectionModel.requester_id == user_id,
                    UserConnectionModel.receiver_id == user_id,
                ),
                UserConnectionModel.deleted_at.is_(None),
            )
            .values(deleted_at=deleted_at)
        )
        self.db.execute(
            delete(UserFollowModel).where(
                or_(
                    UserFollowModel.follower_id == user_id,
                    UserFollowModel.followed_business_id == user_id,
                )
            )
        )
        self.db.execute(
            update(EventParticipantModel)
            .where(
                EventParticipantModel.user_id == user_id,
                EventParticipantModel.status.in_(
                    [
                        EventParticipantStatusEnum.CONFIRMED,
                        EventParticipantStatusEnum.PENDING,
                    ]
                ),
            )
            .values(status=EventParticipantStatusEnum.CANCELLED)
        )

        self.db.commit()

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            user_id=model.user_id,
            user_type=model.user_type,
            email=model.email,
            password_hash=model.password_hash,
            created_at=model.created_at,
            updated_at=model.updated_at,
            role=model.role,
            name=model.name,
            description=model.description,
            user_phone=model.user_phone,
            profile_photo_url=model.profile_photo_url,
            accepted_terms_at=model.accepted_terms_at,
            accepted_terms_version=model.accepted_terms_version,
            password_changed_at=model.password_changed_at,
            deleted_at=model.deleted_at,
        )
