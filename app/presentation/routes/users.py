from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import UserEventAssembler
from app.domain.entities import User
from app.domain.services import (
    DEFAULT_USER_EVENTS_LIMIT,
    MAX_USER_EVENTS_CURSOR_LENGTH,
    MAX_USER_EVENTS_LIMIT,
    MIN_USER_EVENTS_LIMIT,
    UserEventsService,
    UserNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.infrastructure.repository.user_events import SqlAlchemyUserEventsRepository
from app.presentation.dtos import UserEventsOutput
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Users"])


def get_user_events_service(
    db: Annotated[Session, Depends(get_db)],
) -> UserEventsService:
    return UserEventsService(
        user_repository=SqlAlchemyUserRepository(db),
        repository=SqlAlchemyUserEventsRepository(db),
    )


@router.get(
    "/users/{user_id}/events",
    response_model=UserEventsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar os eventos de um usuário",
    description=(
        "Retorna os eventos que o usuário criou ou em que tem presença "
        "confirmada, em ordem crescente de data, incluindo os passados. "
        "Para outra pessoa, só eventos PUBLIC com status PUBLISHED ou "
        "FINISHED; o próprio dono vê todos os seus eventos. Eventos cujo "
        "organizador bloqueou o solicitante não aparecem."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, invalido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "A conta associada ao token foi excluida.",
            "content": {
                "application/json": {"example": {"detail": "Account has been deleted"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "O usuario nao existe, a conta foi excluida ou ele bloqueou "
                "o solicitante."
            ),
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
def list_user_events(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    user_events_service: Annotated[UserEventsService, Depends(get_user_events_service)],
    limit: Annotated[
        int,
        Query(
            ge=MIN_USER_EVENTS_LIMIT,
            le=MAX_USER_EVENTS_LIMIT,
            description="Quantidade maxima de eventos por pagina.",
        ),
    ] = DEFAULT_USER_EVENTS_LIMIT,
    cursor: Annotated[
        str | None,
        Query(
            max_length=MAX_USER_EVENTS_CURSOR_LENGTH,
            description="Cursor opaco devolvido em next_cursor.",
        ),
    ] = None,
) -> UserEventsOutput:
    try:
        page = user_events_service.get_user_events(
            user_id=user_id,
            viewer_id=current_user.user_id,
            limit=limit,
            cursor=cursor,
        )
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from error
    return UserEventAssembler.to_page_dto(page)
