from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.services.cancel_participation import (
    CancelParticipationService,
    ParticipationNotFoundError,
    RequestAlreadyAnsweredError,
)
from app.domain.services.event import EventAlreadyFinishedError
from app.infrastructure.repository import get_db
from app.infrastructure.repository.cancel_participation import (
    SqlAlchemyCancelParticipationRepository,
)
from app.presentation.dependencies.auth import get_current_user

router = APIRouter(prefix="/events", tags=["Events"])


def get_cancel_participation_service(
    db: Annotated[Session, Depends(get_db)],
) -> CancelParticipationService:
    return CancelParticipationService(SqlAlchemyCancelParticipationRepository(db))


@router.delete(
    "/{event_id}/participation",
    response_model=None,
    response_class=Response,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancelar presença ou solicitação de participação",
    description=(
        "Cancela a participação do usuário autenticado sem corpo de entrada. "
        "CONFIRMED e PENDING passam para CANCELLED, sem notificações. "
        "A linha é preservada para permitir uma nova participação pela task 105."
    ),
    responses={
        401: {"description": "Token de acesso ausente ou inválido."},
        404: {
            "description": "Evento ou participação inexistente, ou já cancelada.",
            "content": {
                "application/json": {"example": {"detail": "Participant not found"}}
            },
        },
        409: {
            "description": "Evento encerrado ou solicitação já respondida.",
            "content": {
                "application/json": {
                    "examples": {
                        "finished": {"value": {"detail": "Event already finished"}},
                        "answered": {"value": {"detail": "Request already answered"}},
                    }
                }
            },
        },
    },
)
def cancel_participation(
    event_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        CancelParticipationService, Depends(get_cancel_participation_service)
    ],
) -> Response:
    try:
        service.cancel(event_id, user.user_id)
    except ParticipationNotFoundError as error:
        raise HTTPException(404, "Participant not found") from error
    except EventAlreadyFinishedError as error:
        raise HTTPException(409, "Event already finished") from error
    except RequestAlreadyAnsweredError as error:
        raise HTTPException(409, "Request already answered") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
