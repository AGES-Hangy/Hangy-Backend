from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.domain.assemblers import UserEventsAssembler
from app.domain.entities import User
from app.domain.services import (
    DEFAULT_USER_EVENTS_LIMIT,
    BlockedUserNotFoundError,
    BlockService,
    CannotBlockSelfError,
    InvalidPaginationError,
    InvalidUserEventsTabError,
    UserEventsService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.block import SqlAlchemyBlockRepository
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.infrastructure.repository.user_events import SqlAlchemyUserEventsRepository
from app.presentation.dtos import UserEventsOutput
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Users", "Profile"])


def get_block_service(db: Annotated[Session, Depends(get_db)]) -> BlockService:
    return BlockService(
        repository=SqlAlchemyBlockRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
    )


def get_user_events_service(
    db: Annotated[Session, Depends(get_db)],
) -> UserEventsService:
    return UserEventsService(repository=SqlAlchemyUserEventsRepository(db))


@router.post(
    "/users/{user_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bloquear um usuário",
    description=(
        "Bloqueia o usuário informado: desfaz qualquer conexão existente entre "
        "os dois na mesma operação e passa a esconder os dois lados em perfil, "
        "busca e feed. O bloqueio é unilateral, mas o efeito de invisibilidade "
        "é mútuo. Nenhuma notificação é enviada ao bloqueado."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "O usuário tentou bloquear a si mesmo.",
            "content": {
                "application/json": {"example": {"detail": "Cannot block yourself"}}
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Usuário a bloquear inexistente ou já excluído.",
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
def block_user(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    block_service: Annotated[BlockService, Depends(get_block_service)],
) -> Response:
    assert current_user.user_id is not None
    try:
        block_service.block(current_user.user_id, user_id)
    except CannotBlockSelfError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot block yourself"
        ) from error
    except BlockedUserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
