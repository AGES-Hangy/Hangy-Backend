from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4

from app.domain.entities import PersonProfile, PersonRegistration, User
from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.domain.services.auth import DuplicateEmailError, password_hash

MINIMUM_AGE_YEARS = 18


class InvalidCpfError(Exception):
    """Raised when a CPF fails checksum validation."""


class DuplicateCpfError(Exception):
    """Raised when a CPF is already registered to an active person profile."""


class MinimumAgeError(Exception):
    """Raised when the registering person is under the minimum age."""


class PersonRegistrationRepository(Protocol):
    def get_by_email(self, email: str) -> User | None: ...

    def get_by_cpf(self, cpf: str) -> PersonProfile | None: ...

    def add(self, user: User, profile: PersonProfile) -> User: ...


class RegisterPersonalService:
    def __init__(self, repository: PersonRegistrationRepository) -> None:
        self.repository = repository

    def register(self, registration: PersonRegistration) -> User:
        if not _is_valid_cpf(registration.cpf):
            raise InvalidCpfError

        if _calculate_age(registration.date_of_birth) < MINIMUM_AGE_YEARS:
            raise MinimumAgeError

        if self.repository.get_by_email(registration.email) is not None:
            raise DuplicateEmailError

        if self.repository.get_by_cpf(registration.cpf) is not None:
            raise DuplicateCpfError

        now = datetime.now(UTC)
        user = User(
            user_id=uuid4(),
            user_type=UserTypeEnum.PERSONAL,
            email=registration.email,
            password_hash=password_hash.hash(registration.password),
            created_at=now,
            updated_at=now,
            role=UserRoleEnum.USER,
            name=registration.name,
            user_phone=registration.phone,
            accepted_terms_at=now,
            accepted_terms_version=registration.accepted_terms_version,
        )
        profile = PersonProfile(
            user_id=user.user_id,
            cpf=registration.cpf,
            date_of_birth=registration.date_of_birth,
            country=registration.country,
            state=registration.state,
            city=registration.city,
            updated_at=now,
        )
        return self.repository.add(user, profile)


def _calculate_age(date_of_birth: date, today: date | None = None) -> int:
    today = today or datetime.now(UTC).date()
    had_birthday = (today.month, today.day) >= (date_of_birth.month, date_of_birth.day)
    return today.year - date_of_birth.year - (0 if had_birthday else 1)


def _is_valid_cpf(cpf: str) -> bool:
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False

    digits = [int(digit) for digit in cpf]
    return digits[9] == _cpf_check_digit(digits[:9]) and digits[10] == _cpf_check_digit(
        digits[:10]
    )


def _cpf_check_digit(digits: list[int]) -> int:
    weight = len(digits) + 1
    total = sum(digit * (weight - index) for index, digit in enumerate(digits))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder
