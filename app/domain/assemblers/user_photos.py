from app.domain.entities import UserPhoto, UserPhotosPage
from app.presentation.dtos import (
    UserPhotoEventOutput,
    UserPhotoOutput,
    UserPhotosOutput,
)


class UserPhotosAssembler:
    @staticmethod
    def to_dto(page: UserPhotosPage) -> UserPhotosOutput:
        return UserPhotosOutput(
            items=[UserPhotosAssembler._to_item_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_item_dto(item: UserPhoto) -> UserPhotoOutput:
        return UserPhotoOutput(
            photo_id=item.photo_id,
            photo_url=item.photo_url,
            event=UserPhotoEventOutput(id=item.event_id, title=item.event_title),
            description=item.description,
            created_at=item.created_at,
        )
