from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.entities import (
    BusinessProfile,
    BusinessProfileUpdate,
    EditedBusinessProfile,
    OwnBusinessProfile,
    Unset,
    User,
)
from app.domain.enums import UserTypeEnum
from app.domain.services.register_business import (
    MAX_LATITUDE,
    MAX_LONGITUDE,
    MIN_LATITUDE,
    MIN_LONGITUDE,
    InvalidCoordinatesError,
)
from app.domain.services.user_profile import DescriptionTooLongError

__all__ = [
    "BusinessProfileRepository",
    "BusinessProfileService",
    "NotBusinessProfileError",
]


class NotBusinessProfileError(Exception):
    """Raised when the authenticated user has no business profile."""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class BusinessProfileRepository(Protocol):
    def get_by_user_id(self, user_id: UUID) -> BusinessProfile | None: ...

    def update_profile(
        self, profile: EditedBusinessProfile
    ) -> EditedBusinessProfile: ...


class BusinessProfileService:
    def __init__(
        self,
        repository: BusinessProfileRepository,
        description_max_length: int = 500,
    ) -> None:
        self.repository = repository
        self.description_max_length = description_max_length

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

    def update_profile(
        self, user: User, update: BusinessProfileUpdate
    ) -> EditedBusinessProfile:
        if user.user_type is not UserTypeEnum.BUSINESS or user.user_id is None:
            raise NotBusinessProfileError

        profile = self.repository.get_by_user_id(user.user_id)
        if profile is None:
            raise NotBusinessProfileError

        if (
            isinstance(update.description, str)
            and len(update.description) > self.description_max_length
        ):
            raise DescriptionTooLongError

        if update.location is not Unset.UNSET and update.location is not None:
            if not (
                MIN_LATITUDE <= update.location.latitude <= MAX_LATITUDE
                and MIN_LONGITUDE <= update.location.longitude <= MAX_LONGITUDE
            ):
                raise InvalidCoordinatesError

        current = EditedBusinessProfile(
            user_id=user.user_id,
            business_name=user.name,
            description=user.description,
            address=profile.address,
            latitude=profile.business_latitude,
            longitude=profile.business_longitude,
            updated_at=_as_utc(profile.updated_at),
        )

        changes: dict[str, Any] = {}
        if (
            update.business_name is not Unset.UNSET
            and update.business_name != current.business_name
        ):
            changes["business_name"] = update.business_name

        if (
            update.description is not Unset.UNSET
            and update.description != current.description
        ):
            changes["description"] = update.description

        if update.address is not Unset.UNSET and update.address != current.address:
            changes["address"] = update.address

        if update.location is not Unset.UNSET:
            new_lat = update.location.latitude if update.location is not None else None
            new_lng = update.location.longitude if update.location is not None else None
            if new_lat != current.latitude or new_lng != current.longitude:
                changes["latitude"] = new_lat
                changes["longitude"] = new_lng

        if not changes:
            return current

        edited = replace(current, **changes, updated_at=_now_utc())
        return self.repository.update_profile(edited)
