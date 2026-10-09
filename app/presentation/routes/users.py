from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import UserEventsAssembler
from app.domain.assemblers.users import UsersAssembler
from app.domain.entities import User
from app.domain.services import (
    DEFAULT_USER_EVENTS_LIMIT,
    InvalidPaginationError,
    InvalidUserEventsTabError,
    UserEventsService,
)
from app.domain.services.users import UserNotFoundError, UsersService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.user_events import SqlAlchemyUserEventsRepository
from app.infrastructure.repository.user_profile import SqlAlchemyUserProfileRepository
from app.presentation.dtos import UserEventsOutput
from app.presentation.dtos.users import UserProfileDTO
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Profile"])


def get_user_events_service(
    db: Annotated[Session, Depends(get_db)],
) -> UserEventsService:
    return UserEventsService(repository=SqlAlchemyUserEventsRepository(db))


@router.get(
    "/users/me/events",
    response_model=UserEventsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar os eventos do usuário por aba do perfil",
    description=(
        "`tab=confirmed` lista as participações CONFIRMED em eventos PUBLISHED "
        "que ainda não terminaram, do mais próximo ao mais distante. "
        "`tab=past` lista as participações CONFIRMED em eventos já encerrados "
        "(`ends_at` já passou ou status FINISHED), do mais recente ao mais "
        "antigo. Eventos cancelados ou excluídos não entram. As regras são as "
        "mesmas dos contadores de `GET /users/me/profile`."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`tab` inválida ou parâmetros de paginação inválidos.",
            "content": {"application/json": {"example": {"detail": "Invalid tab"}}},
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "A conta associada ao token foi excluída.",
            "content": {
                "application/json": {"example": {"detail": "Account has been deleted"}}
            },
        },
    },
)
def read_current_user_events(
    tab: Annotated[str, Query(description="Aba do perfil: `confirmed` ou `past`.")],
    current_user: Annotated[User, Depends(get_current_user)],
    user_events_service: Annotated[UserEventsService, Depends(get_user_events_service)],
    limit: Annotated[
        int, Query(description="Tamanho da página (1–100).")
    ] = DEFAULT_USER_EVENTS_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação.")
    ] = None,
) -> UserEventsOutput:
    assert current_user.user_id is not None
    try:
        page = user_events_service.get_user_events(
            current_user.user_id, tab, limit=limit, cursor=cursor
        )
    except InvalidUserEventsTabError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tab"
        ) from error
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    return UserEventsAssembler.to_dto(page)


def get_users_service(db: Annotated[Session, Depends(get_db)]) -> UsersService:
    return UsersService(repository=SqlAlchemyUserProfileRepository(db))


@router.get(
    "/users/{user_id}",
    response_model=UserProfileDTO,
    status_code=status.HTTP_200_OK,
    summary="Obter perfil de um usuário ou estabelecimento",
    description=(
        "Retorna os dados públicos do perfil, incluindo o "
        "estado da conexão/seguimento em relação ao usuário logado."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Usuário não encontrado ou o usuário bloqueou o visitante",
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
def get_user_profile(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    users_service: Annotated[UsersService, Depends(get_users_service)],
) -> UserProfileDTO:
    try:
        profile = users_service.get_profile(
            user_id=user_id, viewer_id=current_user.user_id
        )
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from error

    return UsersAssembler.to_profile_dto(profile)


__all__ = [
    "get_user_events_service",
    "get_user_profile",
    "get_users_service",
    "read_current_user_events",
    "router",
]
