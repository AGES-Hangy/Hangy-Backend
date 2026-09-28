from typing import Protocol
from uuid import UUID

from app.domain.entities import Notification, UnreadNotificationCount


class NotificationRepository(Protocol):
    def mark_all_as_read(self, user_id: UUID) -> None: ...
    def count_unread(self, user_id: UUID) -> int: ...

    def get_by_id(self, notification_id: UUID) -> Notification | None: ...

    def mark_as_read(self, notification_id: UUID) -> None: ...


class NotificationNotFoundError(Exception):
    """Raised when no notification exists with the given id."""


class NotificationNotOwnedError(Exception):
    """Raised when the notification belongs to another user."""


class NotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

    def mark_all_as_read(self, user_id: UUID) -> None:
        self.repository.mark_all_as_read(user_id)

    def get_unread_count(self, user_id: UUID) -> UnreadNotificationCount:
        return UnreadNotificationCount(count=self.repository.count_unread(user_id))

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> None:
        notification = self.repository.get_by_id(notification_id)
        if notification is None:
            raise NotificationNotFoundError
        if notification.user_id != user_id:
            raise NotificationNotOwnedError
        # Idempotent: an already read notification is a success, not an error.
        if not notification.read:
            self.repository.mark_as_read(notification_id)
