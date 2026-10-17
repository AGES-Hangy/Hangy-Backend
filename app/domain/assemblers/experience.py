from uuid import UUID

from app.domain.entities import EventExperience, EventPhotoListItem, EventPhotosPage
from app.presentation.dtos import (
    CreateExperienceOutput,
    EventPhotoAuthorOutput,
    EventPhotoOutput,
    EventPhotosOutput,
)

__all__ = ["ExperienceAssembler"]


class ExperienceAssembler:
    @staticmethod
    def to_created_dto(
        experience: EventExperience, event_id: UUID
    ) -> CreateExperienceOutput:
        if experience.experience_id is None:
            raise ValueError("A persisted experience must have an id")
        return CreateExperienceOutput(
            experience_id=experience.experience_id,
            event_id=event_id,
            description=experience.description,
            images=[],
            created_at=experience.created_at,
        )

    @staticmethod
    def to_photos_dto(page: EventPhotosPage) -> EventPhotosOutput:
        return EventPhotosOutput(
            items=[ExperienceAssembler._to_photo_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_photo_dto(item: EventPhotoListItem) -> EventPhotoOutput:
        photo = item.photo
        return EventPhotoOutput(
            photo_id=photo.photo_id,
            photo_url=photo.photo_url,
            author=EventPhotoAuthorOutput(id=photo.author_id, name=photo.author_name),
            can_delete=item.can_delete,
            created_at=photo.created_at,
        )