from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import BusinessProfile, EditedBusinessProfile, User
from app.domain.services.auth import DuplicateEmailError
from app.domain.services.register_business import DuplicateCnpjError
from app.infrastructure.repository.models import BusinessProfileModel, UserModel
from app.infrastructure.repository.user import SqlAlchemyUserRepository

__all__ = [
    "SqlAlchemyBusinessProfileRepository",
    "SqlAlchemyBusinessRegistrationRepository",
    "to_business_profile_entity",
]


def to_business_profile_entity(model: BusinessProfileModel) -> BusinessProfile:
    return BusinessProfile(
        user_id=model.user_id,
        cnpj=model.cnpj,
        address=model.address,
        updated_at=model.updated_at,
        business_latitude=model.business_latitude,
        business_longitude=model.business_longitude,
    )


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
            select(BusinessProfileModel)
            .join(UserModel, UserModel.user_id == BusinessProfileModel.user_id)
            .where(
                BusinessProfileModel.cnpj == cnpj,
                UserModel.deleted_at.is_(None),
            )
        )
        return to_business_profile_entity(model) if model is not None else None

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
            password_changed_at=user.password_changed_at,
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


class SqlAlchemyBusinessProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _to_entity(model: BusinessProfileModel) -> BusinessProfile:
        return to_business_profile_entity(model)

    def get_by_user_id(self, user_id: UUID) -> BusinessProfile | None:
        model = self.db.scalar(
            select(BusinessProfileModel)
            .join(UserModel, UserModel.user_id == BusinessProfileModel.user_id)
            .where(
                BusinessProfileModel.user_id == user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        if model is None:
            return None
        return self._to_entity(model)

    def update_profile(self, profile: EditedBusinessProfile) -> EditedBusinessProfile:
        self.db.execute(
            update(UserModel)
            .where(
                UserModel.user_id == profile.user_id,
                UserModel.deleted_at.is_(None),
            )
            .values(
                name=profile.business_name,
                description=profile.description,
                updated_at=profile.updated_at,
            )
        )
        self.db.execute(
            update(BusinessProfileModel)
            .where(
                BusinessProfileModel.user_id == profile.user_id,
                BusinessProfileModel.user.has(UserModel.deleted_at.is_(None)),
            )
            .values(
                address=profile.address,
                business_latitude=profile.latitude,
                business_longitude=profile.longitude,
                updated_at=profile.updated_at,
            )
        )
        self.db.commit()
        return profile
