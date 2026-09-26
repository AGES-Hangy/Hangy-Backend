from typing import Protocol
from uuid import UUID


class NotificationRepository(Protocol):
    def mark_all_as_read(self, user_id: UUID) -> None: ...


class NotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self.repository = repository

    def mark_all_as_read(self, user_id: UUID) -> None:
        self.repository.mark_all_as_read(user_id)
