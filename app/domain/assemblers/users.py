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
            connection_id=entity.connection_id,
            connection_direction=entity.connection_direction,
            is_following=entity.is_following,
            connections_count=entity.connections_count,
            followers_count=entity.followers_count,
        )


__all__ = ["UsersAssembler"]
