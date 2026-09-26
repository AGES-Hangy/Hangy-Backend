from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.services import NotificationService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Notifications"])


def get_notification_service(
    db: Annotated[Session, Depends(get_db)],
) -> NotificationService:
    return NotificationService(repository=SqlAlchemyNotificationRepository(db))


@router.patch("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_notifications_as_read(
    current_user: Annotated[User, Depends(get_current_user)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
) -> None:
    notification_service.mark_all_as_read(current_user.user_id)
