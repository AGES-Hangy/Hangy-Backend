from app.domain.entities.user_profile import UserProfile
from app.presentation.dtos.user_profile import (
    ProfileTagOutput,
    UserProfileCountsOutput,
    UserProfileDataOutput,
    UserProfileOutput,
)

__all__ = ["UserProfileAssembler"]


class UserProfileAssembler:
    @staticmethod
    def to_dto(profile: UserProfile) -> UserProfileOutput:
        return UserProfileOutput(
            profile=UserProfileDataOutput(
                id=profile.user_id,
                name=profile.name,
                description=profile.description,
                photo_url=profile.photo_url,
                tags=[
                    ProfileTagOutput(id=tag.tag_id, name=tag.tag_name)
                    for tag in profile.tags
                    if tag.tag_id is not None
                ],
                connections_count=profile.connections_count,
            ),
            counts=UserProfileCountsOutput(
                past=profile.counts.past,
                confirmed=profile.counts.confirmed,
                photos=profile.counts.photos,
            ),
        )
