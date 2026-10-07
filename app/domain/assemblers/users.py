from app.domain.entities.user_profile import UserProfileData
from app.presentation.dtos.users import UserProfileDTO, UserProfileTagDTO


class UsersAssembler:
    @staticmethod
    def to_profile_dto(entity: UserProfileData) -> UserProfileDTO:
        return UserProfileDTO(
            id=entity.user_id,
            user_type=entity.user_type,
            name=entity.name,
            description=entity.description,
            photo_url=entity.photo_url,
            tags=[
                UserProfileTagDTO(id=tag.tag_id, name=tag.tag_name)
                for tag in entity.tags
            ],
            connection_status=entity.connection_status,
            is_following=entity.is_following,
            is_blocked=entity.is_blocked,
            connections_count=entity.connections_count,
        )


__all__ = ["UsersAssembler"]
