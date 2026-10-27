from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app.domain.assemblers import AdminUsersAssembler
from app.domain.enums import ModerationStatusEnum
from app.domain.services import (
    DEFAULT_ADMIN_USERS_LIMIT,
    MAX_ADMIN_USERS_SEARCH_LENGTH,
    AdminUsersService,
    InvalidPaginationError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.admin_users import SqlAlchemyAdminUsersRepository
from app.presentation.dependencies.admin import require_admin
from app.presentation.dtos import AdminUsersOutput

router = APIRouter(tags=["Admin"])


def _parse_limit(value: str | int) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error


def get_admin_users_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminUsersService:
    return AdminUsersService(repository=SqlAlchemyAdminUsersRepository(db))


@router.get(
    "/admin/users",
    response_model=AdminUsersOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
    summary="Listar usuários para a gestão de moderação",
    description=(
        "Lista, do cadastro mais recente para o mais antigo, as contas pessoais "
        "e de estabelecimento não excluídas, com o status de moderação derivado "
        "(`BANNED` se banida; `SUSPENDED` se a suspensão ainda não terminou; "
        "senão `ACTIVE`), o número de eventos criados e o de denúncias não "
        "arquivadas contra o perfil ou contra eventos do usuário. `search` "
        "busca por trecho do nome ou do e-mail, sem diferenciar maiúsculas. "
        "Exige Bearer token de um usuário com `role = ADMIN`."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`limit` ou `cursor` inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid pagination parameters"}
                }
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
        status.HTTP_403_FORBIDDEN: {
            "description": "Usuário autenticado, mas `role != ADMIN`.",
            "content": {
                "application/json": {"example": {"detail": "Admin access required"}}
            },
        },
    },
)
def read_admin_users(
    admin_users_service: Annotated[AdminUsersService, Depends(get_admin_users_service)],
    moderation_status: Annotated[
        ModerationStatusEnum | None,
        Query(alias="status", description="Filtra pelo status de moderação."),
    ] = None,
    search: Annotated[
        str | None,
        Query(
            max_length=MAX_ADMIN_USERS_SEARCH_LENGTH,
            description="Trecho do nome ou do e-mail.",
        ),
    ] = None,
    limit: Annotated[
        int,
        BeforeValidator(_parse_limit),
        Query(description="Tamanho da página (1–100)."),
    ] = DEFAULT_ADMIN_USERS_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação.")
    ] = None,
) -> AdminUsersOutput:
    try:
        page = admin_users_service.get_users(
            status=moderation_status, search=search, limit=limit, cursor=cursor
        )
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    return AdminUsersAssembler.to_dto(page)
