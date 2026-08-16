from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.services import DuplicateUsernameError
from app.infrastructure.repository.models import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> User | None:
        model = self.db.get(UserModel, user_id)
        return self._to_entity(model) if model is not None else None

    def get_by_username(self, username: str) -> User | None:
        model = self.db.scalar(
            select(UserModel).where(UserModel.username == username)
        )
        return self._to_entity(model) if model is not None else None

    def add(self, user: User) -> User:
        model = UserModel(
            username=user.username,
            password_hash=user.password_hash,
            created_at=user.created_at,
        )
        self.db.add(model)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            raise DuplicateUsernameError from error
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            username=model.username,
            password_hash=model.password_hash,
            created_at=model.created_at,
        )
