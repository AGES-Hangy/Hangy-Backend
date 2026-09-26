from app.domain.entities import UnreadNotificationCount
from app.presentation.dtos import UnreadNotificationCountOutput


class NotificationAssembler:
    @staticmethod
    def to_unread_count_dto(
        unread_count: UnreadNotificationCount,
    ) -> UnreadNotificationCountOutput:
        return UnreadNotificationCountOutput(unread_count=unread_count.count)
