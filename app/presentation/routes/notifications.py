from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.domain.assemblers import NotificationAssembler
from app.domain.entities import User
from app.domain.services import (
    NotificationNotFoundError,
    NotificationNotOwnedError,
    NotificationService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.presentation.dtos import UnreadNotificationCountOutput
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Notifications"])


def get_notification_service(
    db: Annotated[Session, Depends(get_db)],
) -> NotificationService:
    return NotificationService(repository=SqlAlchemyNotificationRepository(db))


@router.get(
    "/notifications/unread-count",
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


@router.patch(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Marcar uma notificação como lida",
    description=(
        "Marca a notificação informada como lida, desde que ela pertença ao "
        "usuário autenticado. A operação é idempotente: marcar uma notificação "
        "já lida também retorna 204."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "A notificação pertence a outro usuário.",
            "content": {
                "application/json": {"example": {"detail": "Not your notification"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Notificação não encontrada.",
            "content": {
                "application/json": {"example": {"detail": "Notification not found"}}
            },
        },
    },
)
def mark_notification_as_read(
    notification_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
) -> Response:
    try:
        notification_service.mark_as_read(notification_id, current_user.user_id)
    except NotificationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        ) from error
    except NotificationNotOwnedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your notification",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
