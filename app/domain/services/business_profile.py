from typing import Protocol
from uuid import UUID

from app.domain.entities import BusinessProfile, OwnBusinessProfile, User
from app.domain.enums import UserTypeEnum


class NotBusinessProfileError(Exception):
    """Raised when the authenticated user has no business profile."""


class BusinessProfileRepository(Protocol):
    def get_by_user_id(self, user_id: UUID) -> BusinessProfile | None: ...


class BusinessProfileService:
    def __init__(self, repository: BusinessProfileRepository) -> None:
        self.repository = repository

    def get_own_profile(self, user: User) -> OwnBusinessProfile:
        if user.user_type is not UserTypeEnum.BUSINESS or user.user_id is None:
            raise NotBusinessProfileError

        profile = self.repository.get_by_user_id(user.user_id)
        if profile is None:
            raise NotBusinessProfileError

        return OwnBusinessProfile(
            user_id=user.user_id,
            cnpj=profile.cnpj,
            address=profile.address,
            business_name=user.name,
            description=user.description,
            phone=user.user_phone,
            latitude=profile.business_latitude,
            longitude=profile.business_longitude,
        )
