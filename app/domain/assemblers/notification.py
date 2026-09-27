"""NotificationAssembler — converts domain entities to response DTOs."""

__all__ = ["NotificationAssembler"]

from app.domain.entities import Notification
from app.presentation.dtos.notification import (
    NotificationItemResponse,
    NotificationsPaginatedResponse,
)


class NotificationAssembler:
    @staticmethod
    def to_item_dto(notification: Notification) -> NotificationItemResponse:
        assert notification.notification_id is not None
        return NotificationItemResponse(
            notification_id=notification.notification_id,
            type=notification.type,
            read=notification.read,
            created_at=notification.created_at,
            payload=notification.payload,
        )

    @staticmethod
    def to_paginated_dto(
        items: list[Notification],
        next_cursor: str | None,
        unread_count: int,
    ) -> NotificationsPaginatedResponse:
        return NotificationsPaginatedResponse(
            items=[NotificationAssembler.to_item_dto(n) for n in items],
            next_cursor=next_cursor,
            unread_count=unread_count,
        )
