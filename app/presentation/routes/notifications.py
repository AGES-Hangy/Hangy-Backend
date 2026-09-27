from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.domain.assemblers import NotificationAssembler
from app.domain.entities import User
from app.domain.services import NotificationService
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
