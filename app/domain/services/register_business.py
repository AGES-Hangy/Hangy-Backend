from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.domain.entities import BusinessProfile, BusinessRegistration, User
from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.domain.services.auth import DuplicateEmailError, password_hash

MIN_LATITUDE, MAX_LATITUDE = -90.0, 90.0
MIN_LONGITUDE, MAX_LONGITUDE = -180.0, 180.0

_CNPJ_FIRST_DIGIT_WEIGHTS = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_SECOND_DIGIT_WEIGHTS = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


class InvalidCnpjError(Exception):
    """Raised when a CNPJ fails checksum validation."""


class DuplicateCnpjError(Exception):
    """Raised when a CNPJ is already registered to an active business profile."""


class InvalidCoordinatesError(Exception):
    """Raised when the business location falls outside valid coordinate ranges."""


class BusinessRegistrationRepository(Protocol):
    def get_by_email(self, email: str) -> User | None: ...

    def get_by_cnpj(self, cnpj: str) -> BusinessProfile | None: ...

    def add(self, user: User, profile: BusinessProfile) -> User: ...


class RegisterBusinessService:
    def __init__(self, repository: BusinessRegistrationRepository) -> None:
        self.repository = repository

    def register(self, registration: BusinessRegistration) -> User:
        if not _is_valid_cnpj(registration.cnpj):
            raise InvalidCnpjError

        if not _has_valid_coordinates(registration.latitude, registration.longitude):
            raise InvalidCoordinatesError

        if self.repository.get_by_email(registration.email) is not None:
            raise DuplicateEmailError

        if self.repository.get_by_cnpj(registration.cnpj) is not None:
            raise DuplicateCnpjError

        now = datetime.now(UTC)
        user = User(
            user_id=uuid4(),
            user_type=UserTypeEnum.BUSINESS,
            email=registration.email,
            password_hash=password_hash.hash(registration.password),
            created_at=now,
            updated_at=now,
            role=UserRoleEnum.USER,
            name=registration.business_name,
            description=registration.description,
            user_phone=registration.phone,
            accepted_terms_at=now,
            accepted_terms_version=registration.accepted_terms_version,
        )
        profile = BusinessProfile(
            user_id=user.user_id,
            cnpj=registration.cnpj,
            address=registration.address,
            updated_at=now,
            business_latitude=registration.latitude,
            business_longitude=registration.longitude,
        )
        return self.repository.add(user, profile)


def _has_valid_coordinates(latitude: float, longitude: float) -> bool:
    return (
        MIN_LATITUDE <= latitude <= MAX_LATITUDE
        and MIN_LONGITUDE <= longitude <= MAX_LONGITUDE
    )


def _is_valid_cnpj(cnpj: str) -> bool:
    if len(cnpj) != 14 or not cnpj.isdigit() or len(set(cnpj)) == 1:
        return False

    digits = [int(digit) for digit in cnpj]
    return digits[12] == _cnpj_check_digit(
        digits[:12], _CNPJ_FIRST_DIGIT_WEIGHTS
    ) and digits[13] == _cnpj_check_digit(digits[:13], _CNPJ_SECOND_DIGIT_WEIGHTS)


def _cnpj_check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    total = sum(digit * weight for digit, weight in zip(digits, weights, strict=True))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder
