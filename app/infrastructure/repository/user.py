from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.enums import EventStatusEnum
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel


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

    def has_future_events_as_organizer(self, user_id: UUID) -> bool:
        now = datetime.now()
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
        model.name = None
        model.description = None
        model.user_phone = None
        model.profile_photo_url = None
        model.deleted_at = deleted_at
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
