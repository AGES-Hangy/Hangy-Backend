from app.domain.entities import BlockedUsersPage
from app.presentation.dtos.block import BlockedUserOutput, BlockedUsersOutput


class BlockAssembler:
    @staticmethod
    def to_blocked_users_dto(page: BlockedUsersPage) -> BlockedUsersOutput:
        return BlockedUsersOutput(
            items=[
                BlockedUserOutput(
                    user_id=item.user_id,
                    name=item.name,
                    photo_url=item.photo_url,
                    blocked_at=item.blocked_at,
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
