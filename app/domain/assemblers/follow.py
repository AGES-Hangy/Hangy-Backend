from app.domain.entities import FollowedBusiness, FollowedBusinessesPage
from app.presentation.dtos import FollowedBusinessOutput, FollowingOutput

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
