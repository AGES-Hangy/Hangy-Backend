from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.domain.assemblers import UserEventsAssembler
from app.domain.assemblers.users import UsersAssembler
from app.domain.entities import User
from app.domain.services import (
    DEFAULT_USER_EVENTS_LIMIT,
    BlockedUserNotFoundError,
    BlockService,
    CannotBlockSelfError,
    InvalidPaginationError,
    InvalidUserEventsTabError,
    UserAlreadyBlockedError,
    UserEventsService,
)
from app.domain.services.users import UserNotFoundError, UsersService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.block import SqlAlchemyBlockRepository
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.infrastructure.repository.user_events import SqlAlchemyUserEventsRepository
from app.infrastructure.repository.user_profile import SqlAlchemyUserProfileRepository
from app.presentation.dtos import UserEventsOutput, UserEventsTabsOutput
from app.presentation.dtos.users import UserProfileDTO
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Profile"])


def get_block_service(db: Annotated[Session, Depends(get_db)]) -> BlockService:
    return BlockService(
        repository=SqlAlchemyBlockRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
    )


def get_user_events_service(
    db: Annotated[Session, Depends(get_db)],
    block_service: Annotated[BlockService, Depends(get_block_service)],
) -> UserEventsService:
    return UserEventsService(
        repository=SqlAlchemyUserEventsRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
        block_checker=block_service,
    )


@router.post(
    "/users/{user_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Users"],
    summary="Bloquear um usuário",
    description=(
        "Bloqueia o usuário informado e desfaz, na mesma operação, a conexão "
        "ou solicitação pendente entre os dois. O bloqueio é unilateral, mas "
        "o efeito é mútuo: `GET /users/{user_id}` passa a devolver 404 para os "
        "dois lados, nenhum dos dois consegue enviar solicitação de conexão "
        "ao outro e os eventos de um deixam de aparecer no feed do outro. "
        "Nenhuma notificação é enviada ao bloqueado."
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
        status.HTTP_409_CONFLICT: {
            "description": "O usuário informado já está bloqueado.",
            "content": {
                "application/json": {"example": {"detail": "User already blocked"}}
            },
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
    except UserAlreadyBlockedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User already blocked"
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


def get_users_service(
    db: Annotated[Session, Depends(get_db)],
    block_service: Annotated[BlockService, Depends(get_block_service)],
) -> UsersService:
    return UsersService(
        repository=SqlAlchemyUserProfileRepository(db), block_checker=block_service
    )


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
            "description": (
                "Usuário não encontrado, ou existe bloqueio entre ele e o "
                "visitante, em qualquer sentido (mesmo erro nos dois casos)."
            ),
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


@router.get(
    "/users/{user_id}/events",
    response_model=UserEventsTabsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar os eventos de um perfil por categoria",
    description=(
        "Sem `tab`, devolve a primeira página de cada categoria permitida ao "
        "solicitante. Com `tab` e `cursor` juntos, devolve só a continuação "
        "daquela categoria e as demais vêm `null`. Conta pessoal no próprio "
        "perfil vê `history`, `created`, `interests` e `confirmed`; "
        "estabelecimento no próprio perfil e qualquer um no perfil de outro "
        "veem `history` e `created`. No perfil de outro só entram eventos "
        "PUBLIC e `participation_status` é sempre `null`. Categoria não "
        "permitida vem `null`; permitida e vazia vem com `items` vazio. Eventos "
        "de um organizador com bloqueio entre ele e o solicitante não aparecem."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": (
                "`Invalid tab`: tab desconhecida, não permitida ao solicitante "
                "ou enviada sem cursor (e vice-versa). `Invalid pagination "
                "parameters`: limit fora de 1–100 ou cursor malformado."
            ),
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
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "O usuário não existe, a conta foi excluída ou há um bloqueio "
                "entre ele e o solicitante, em qualquer direção."
            ),
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
    },
)
def list_user_events(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    user_events_service: Annotated[UserEventsService, Depends(get_user_events_service)],
    tab: Annotated[
        str | None,
        Query(
            description=(
                "`history`, `created`, `interests` ou `confirmed`. "
                "Só é aceita junto com `cursor`."
            )
        ),
    ] = None,
    limit: Annotated[
        int, Query(description="Tamanho da página por categoria (1–100).")
    ] = DEFAULT_USER_EVENTS_LIMIT,
    cursor: Annotated[
        str | None,
        Query(description="`next_cursor` devolvido pela categoria de `tab`."),
    ] = None,
) -> UserEventsTabsOutput:
    try:
        tabs = user_events_service.get_profile_events(
            user_id, current_user, tab=tab, limit=limit, cursor=cursor
        )
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from error
    except InvalidUserEventsTabError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tab"
        ) from error
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    return UserEventsAssembler.to_tabs_dto(tabs)


__all__ = [
    "block_user",
    "get_block_service",
    "get_user_events_service",
    "get_user_profile",
    "get_users_service",
    "list_user_events",
    "read_current_user_events",
    "router",
]
