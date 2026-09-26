from typing import Protocol
from uuid import UUID

from app.domain.entities import UnreadNotificationCount


class NotificationRepository(Protocol):
    def mark_all_as_read(self, user_id: UUID) -> None: ...
    def count_unread(self, user_id: UUID) -> int: ...


class NotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

    def mark_all_as_read(self, user_id: UUID) -> None:
        self.repository.mark_all_as_read(user_id)

    def get_unread_count(self, user_id: UUID) -> UnreadNotificationCount:
        return UnreadNotificationCount(count=self.repository.count_unread(user_id))
