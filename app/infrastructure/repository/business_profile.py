from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import BusinessProfile, User
from app.domain.services.auth import DuplicateEmailError
from app.domain.services.register_business import DuplicateCnpjError
from app.infrastructure.repository.models import BusinessProfileModel, UserModel
from app.infrastructure.repository.user import SqlAlchemyUserRepository


class SqlAlchemyBusinessRegistrationRepository:
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

    def get_by_cnpj(self, cnpj: str) -> BusinessProfile | None:
        model = self.db.scalar(
            select(BusinessProfileModel).where(BusinessProfileModel.cnpj == cnpj)
        )
        return self._to_entity(model) if model is not None else None

    def add(self, user: User, profile: BusinessProfile) -> User:
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
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        profile_model = BusinessProfileModel(
            user_id=profile.user_id,
            cnpj=profile.cnpj,
            address=profile.address,
            business_latitude=profile.business_latitude,
            business_longitude=profile.business_longitude,
            updated_at=profile.updated_at,
        )
        self.db.add(user_model)
        self.db.add(profile_model)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            if self.get_by_cnpj(profile.cnpj) is not None:
                raise DuplicateCnpjError from error
            raise DuplicateEmailError from error
        self.db.refresh(user_model)
        return SqlAlchemyUserRepository._to_entity(user_model)

    @staticmethod
    def _to_entity(model: BusinessProfileModel) -> BusinessProfile:
        return BusinessProfile(
            user_id=model.user_id,
            cnpj=model.cnpj,
            address=model.address,
            updated_at=model.updated_at,
            business_latitude=model.business_latitude,
            business_longitude=model.business_longitude,
        )
