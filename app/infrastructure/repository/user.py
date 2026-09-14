from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.services import DuplicateEmailError
from app.infrastructure.repository.models import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: UUID) -> User | None:
        model = self.db.scalar(
            select(UserModel).where(
                UserModel.user_id == user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def get_by_email(self, email: str) -> User | None:
        model = self.db.scalar(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def add(self, user: User) -> User:
        model = UserModel(
            user_type=user.user_type,
            role=user.role,
            email=user.email,
            password_hash=user.password_hash,
            name=user.name,
            description=user.description,
            user_phone=user.user_phone,
            profile_photo_url=user.profile_photo_url,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        self.db.add(model)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise DuplicateEmailError from error
        self.db.refresh(model)
        return self._to_entity(model)

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
            deleted_at=model.deleted_at,
        )
