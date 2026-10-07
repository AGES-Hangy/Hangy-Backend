from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    BusinessProfile,
    EditedPersonProfile,
    PersonProfile,
    PersonProfileUpdate,
    Tag,
    Unset,
    User,
    UserProfile,
    UserProfileCounts,
)
from app.domain.enums import UserTypeEnum


class UserProfileRepository(Protocol):
    def get_person_profile(self, user_id: UUID) -> PersonProfile | None: ...

    def get_business_profile(self, user_id: UUID) -> BusinessProfile | None: ...

    def get_profile_counts(self, user_id: UUID) -> UserProfileCounts: ...

    def update_person_profile(
        self, profile: EditedPersonProfile
    ) -> EditedPersonProfile: ...


class UserProfileTagsRepository(Protocol):
    def list_user_tags(self, user_id: UUID) -> list[Tag]: ...


class NotAPersonalProfileError(Exception):
    """Raised when a business account tries to edit a personal profile."""


class DescriptionTooLongError(Exception):
    """Raised when the bio exceeds the configured maximum length."""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class UserProfileService:
    def __init__(
        self,
        repository: UserProfileRepository,
        tags_repository: UserProfileTagsRepository,
        description_max_length: int = 500,
    ) -> None:
        self.repository = repository
        self.tags_repository = tags_repository
        self.description_max_length = description_max_length

    def get_profile_for_user(
        self, user: User
    ) -> PersonProfile | BusinessProfile | None:
        if user.user_id is None:
            raise ValueError("An authenticated user must have an id")
        if user.user_type is UserTypeEnum.PERSONAL:
            return self.repository.get_person_profile(user.user_id)
        return self.repository.get_business_profile(user.user_id)

    def get_profile(self, user: User) -> UserProfile:
        """The profile screen header plus the counters of its tabs."""
        if user.user_id is None:
            raise ValueError("An authenticated user must have an id")
        # The user was already loaded (and checked as active) by authentication,
        # so only the tags and the counters still need the database.
        return UserProfile(
            user_id=user.user_id,
            name=user.name,
            description=user.description,
            photo_url=user.profile_photo_url,
            tags=tuple(self.tags_repository.list_user_tags(user.user_id)),
            counts=self.repository.get_profile_counts(user.user_id),
        )

    def update_profile(
        self, user: User, update: PersonProfileUpdate
    ) -> EditedPersonProfile:
        """Apply the fields sent in a partial update to a personal profile."""
        if user.user_id is None:
            raise ValueError("An authenticated user must have an id")
        if user.user_type is not UserTypeEnum.PERSONAL:
            raise NotAPersonalProfileError
        if (
            isinstance(update.description, str)
            and len(update.description) > self.description_max_length
        ):
            raise DescriptionTooLongError

        person_profile = self.repository.get_person_profile(user.user_id)
        if person_profile is None:
            raise NotAPersonalProfileError

        current = EditedPersonProfile(
            user_id=user.user_id,
            name=user.name,
            description=user.description,
            state=person_profile.state,
            city=person_profile.city,
            updated_at=_as_utc(person_profile.updated_at),
        )
        changes = {
            field: value
            for field, value in (
                ("name", update.name),
                ("description", update.description),
                ("state", update.state),
                ("city", update.city),
            )
            if value is not Unset.UNSET and value != getattr(current, field)
        }
        # Resending the current values is not an edit, so updated_at keeps
        # recording the last time the profile actually changed.
        if not changes:
            return current

        edited = replace(current, **changes, updated_at=_now_utc())
        return self.repository.update_person_profile(edited)
