from app.domain.entities import AdminUsersPage
from app.presentation.dtos.admin_users import AdminUserOutput, AdminUsersOutput


class AdminUsersAssembler:
    @staticmethod
    def to_dto(page: AdminUsersPage) -> AdminUsersOutput:
        return AdminUsersOutput(
            items=[
                AdminUserOutput(
                    user_id=item.user_id,
                    name=item.name,
                    moderation_status=item.moderation_status,
                    suspended_until=item.suspended_until,
                    event_count=item.event_count,
                    report_count=item.report_count,
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )
