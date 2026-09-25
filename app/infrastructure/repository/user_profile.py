from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.entities import BusinessProfile, PersonProfile
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    PersonProfileModel,
)


class SqlAlchemyUserProfileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_person_profile(self, user_id: UUID) -> PersonProfile | None:
        model = self.db.get(PersonProfileModel, user_id)
        return self._to_person_entity(model) if model is not None else None

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None:
        model = self.db.get(BusinessProfileModel, user_id)
        return self._to_business_entity(model) if model is not None else None

    @staticmethod
    def _to_person_entity(model: PersonProfileModel) -> PersonProfile:
        return PersonProfile(
            user_id=model.user_id,
            cpf=model.cpf,
            date_of_birth=model.date_of_birth,
            country=model.country,
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
