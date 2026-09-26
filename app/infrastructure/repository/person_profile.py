from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import PersonProfile, User
from app.domain.services.auth import DuplicateEmailError
from app.domain.services.register_personal import DuplicateCpfError
from app.infrastructure.repository.models import PersonProfileModel, UserModel
from app.infrastructure.repository.user import SqlAlchemyUserRepository


class SqlAlchemyPersonRegistrationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        model = self.db.scalar(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.deleted_at.is_(None),
            )
        )
        return SqlAlchemyUserRepository._to_entity(model) if model is not None else None

    def get_by_cpf(self, cpf: str) -> PersonProfile | None:
        model = self.db.scalar(
            select(PersonProfileModel).where(PersonProfileModel.cpf == cpf)
        )
        return self._to_entity(model) if model is not None else None

    def add(self, user: User, profile: PersonProfile) -> User:
        user_model = UserModel(
            user_id=user.user_id,
            user_type=user.user_type,
            role=user.role,
            email=user.email,
            password_hash=user.password_hash,
            name=user.name,
            description=user.description,
            user_phone=user.user_phone,
            profile_photo_url=user.profile_photo_url,
            accepted_terms_at=user.accepted_terms_at,
            accepted_terms_version=user.accepted_terms_version,
            password_changed_at=user.password_changed_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        profile_model = PersonProfileModel(
            user_id=profile.user_id,
            cpf=profile.cpf,
            date_of_birth=profile.date_of_birth,
            country=profile.country,
            state=profile.state,
            city=profile.city,
            updated_at=profile.updated_at,
        )
        self.db.add(user_model)
        self.db.add(profile_model)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            if self.get_by_cpf(profile.cpf) is not None:
                raise DuplicateCpfError from error
            raise DuplicateEmailError from error
        self.db.refresh(user_model)
        return SqlAlchemyUserRepository._to_entity(user_model)

    @staticmethod
    def _to_entity(model: PersonProfileModel) -> PersonProfile:
        return PersonProfile(
            user_id=model.user_id,
            cpf=model.cpf,
            date_of_birth=model.date_of_birth,
            country=model.country,
            state=model.state,
            city=model.city,
            updated_at=model.updated_at,
        )
