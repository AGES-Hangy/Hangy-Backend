"""Notifications router — GET /notifications, PATCH /notifications/{id}/read, etc."""

__all__ = ["router"]

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers.notification import NotificationAssembler
from app.domain.entities import User
from app.domain.services import (
    InvalidPaginationError,
    NotificationNotFoundError,
    NotificationService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.presentation.dtos.notification import (
    NotificationsPaginatedResponse,
    UnreadNotificationCountOutput,
)
from app.presentation.routes.auth import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_notification_service(
    db: Annotated[Session, Depends(get_db)],
) -> NotificationService:
    return NotificationService(repository=SqlAlchemyNotificationRepository(db))


@router.get(
    "/unread-count",
    response_model=UnreadNotificationCountOutput,
    status_code=status.HTTP_200_OK,
    summary="Contar notificações não lidas",
    description=(
        "Retorna quantas notificações ainda não lidas o usuário autenticado "
        "possui. Usado pelo badge do sino."
    ),
)
def read_unread_notification_count(
    current_user: Annotated[User, Depends(get_current_user)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
) -> UnreadNotificationCountOutput:
    unread_count = notification_service.get_unread_count(current_user.user_id)
    return NotificationAssembler.to_unread_count_dto(unread_count)


@router.get(
    "",
    response_model=NotificationsPaginatedResponse,
    status_code=status.HTTP_200_OK,
    summary="List notifications for the authenticated user",
)
def list_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
    unread_only: Annotated[
        bool, Query(description="Return only unread notifications")
    ] = False,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1–100)")] = 20,
    cursor: Annotated[str | None, Query(description="Opaque pagination cursor")] = None,
) -> NotificationsPaginatedResponse:
    assert current_user.user_id is not None
    try:
        items, next_cursor, unread_count = notification_service.list_notifications(
            current_user.user_id,
            limit=limit,
            cursor=cursor,
            unread_only=unread_only,
        )
    except InvalidPaginationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from exc

    return NotificationAssembler.to_paginated_dto(items, next_cursor, unread_count)


@router.patch(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a single notification as read",
)
def mark_notification_as_read(
    notification_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
) -> None:
    assert current_user.user_id is not None
    try:
        notification_service.mark_as_read(notification_id, current_user.user_id)
    except NotificationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Notification not found or does not belong to the current user",
        ) from exc


@router.patch(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark all notifications as read",
)
def mark_all_notifications_as_read(
    current_user: Annotated[User, Depends(get_current_user)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
) -> None:
    assert current_user.user_id is not None
    notification_service.mark_all_as_read(current_user.user_id)
