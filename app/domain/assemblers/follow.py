from app.domain.entities import (
    BusinessFollower,
    BusinessFollowersPage,
    FollowedBusiness,
    FollowedBusinessesPage,
)
from app.presentation.dtos import (
    BusinessFollowerOutput,
    BusinessFollowersOutput,
    BusinessFollowerTagOutput,
    FollowedBusinessOutput,
    FollowingOutput,
)

__all__ = ["FollowAssembler"]


class FollowAssembler:
    @staticmethod
    def to_following_dto(page: FollowedBusinessesPage) -> FollowingOutput:
        return FollowingOutput(
            items=[FollowAssembler._to_item_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_item_dto(item: FollowedBusiness) -> FollowedBusinessOutput:
        return FollowedBusinessOutput(
            user_id=item.user_id,
            business_name=item.business_name,
            photo_url=item.photo_url,
            city=item.city,
            followed_at=item.followed_at,
        )

    @staticmethod
    def to_followers_dto(page: BusinessFollowersPage) -> BusinessFollowersOutput:
        return BusinessFollowersOutput(
            items=[FollowAssembler._to_follower_dto(item) for item in page.items],
            total=page.total,
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_follower_dto(item: BusinessFollower) -> BusinessFollowerOutput:
        return BusinessFollowerOutput(
            user_id=item.user_id,
            name=item.name,
            photo_url=item.photo_url,
            tags=[
                BusinessFollowerTagOutput(id=tag.id, name=tag.name) for tag in item.tags
            ],
        )
