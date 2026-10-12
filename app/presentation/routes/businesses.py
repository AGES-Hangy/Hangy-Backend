from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.domain.assemblers import FollowAssembler
from app.domain.entities import User
from app.domain.services import InvalidPaginationError
from app.domain.services.follow import (
    DEFAULT_FOLLOWING_LIMIT,
    BusinessNotFoundError,
    FollowService,
    TargetNotBusinessError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.follow import SqlAlchemyFollowRepository
from app.presentation.dtos import FollowingOutput
from app.presentation.routes.auth import credentials_exception, get_current_user

router = APIRouter(prefix="/businesses", tags=["Businesses"])
# The path lives under /users/me, so it cannot use the /businesses prefix.
following_router = APIRouter(tags=["Businesses"])


def get_follow_service(db: Annotated[Session, Depends(get_db)]) -> FollowService:
    return FollowService(SqlAlchemyFollowRepository(db))


@router.post(
    "/{business_id}/follow",
    response_model=None,
    response_class=Response,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Seguir um estabelecimento",
    description=(
        "O usuário autenticado passa a seguir o estabelecimento imediatamente, "
        "sem aprovação, status ou notificação. Idempotente: seguir quem já é "
        "seguido também devolve 204."
    ),
    responses={
        401: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        403: {
            "description": "O alvo é um perfil pessoal.",
            "content": {
                "application/json": {
                    "example": {"detail": "Target is not a business profile"}
                }
            },
        },
        404: {
            "description": "Estabelecimento inexistente ou excluído.",
            "content": {
                "application/json": {"example": {"detail": "Business not found"}}
            },
        },
    },
)
def follow_business(
    business_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> Response:
    if current_user.user_id is None:
        raise credentials_exception
    try:
        service.follow(current_user.user_id, business_id)
    except BusinessNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found") from error
    except TargetNotBusinessError as error:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Target is not a business profile"
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{business_id}/follow",
    response_model=None,
    response_class=Response,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deixar de seguir um estabelecimento",
    description=(
        "O usuário autenticado deixa de seguir o estabelecimento. Idempotente: "
        "deixar de seguir quem não é seguido também devolve 204."
    ),
    responses={
        401: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        404: {
            "description": "Estabelecimento inexistente ou excluído.",
            "content": {
                "application/json": {"example": {"detail": "Business not found"}}
            },
        },
    },
)
def unfollow_business(
    business_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FollowService, Depends(get_follow_service)],
) -> Response:
    if current_user.user_id is None:
        raise credentials_exception
    try:
        service.unfollow(current_user.user_id, business_id)
    except (BusinessNotFoundError, TargetNotBusinessError) as error:
        # A personal profile is never a followable business, so for this
        # endpoint it is indistinguishable from a missing one.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@following_router.get(
    "/users/me/following",
    response_model=FollowingOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar os estabelecimentos que o usuário segue",
    description=(
        "Lista os estabelecimentos seguidos pelo usuário autenticado, do mais "
        "recente para o mais antigo. Contas excluídas (soft delete) não "
        "aparecem. Paginação por cursor opaco (`next_cursor`)."
    ),
    responses={
        400: {
            "description": "`limit` ou `cursor` inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid pagination parameters"}
                }
            },
        },
        401: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
    },
)
def read_following(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FollowService, Depends(get_follow_service)],
    limit: Annotated[
        int, Query(description="Tamanho da página (1–100).")
    ] = DEFAULT_FOLLOWING_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação.")
    ] = None,
) -> FollowingOutput:
    if current_user.user_id is None:
        raise credentials_exception
    try:
        page = service.get_following(current_user.user_id, limit=limit, cursor=cursor)
    except InvalidPaginationError as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid pagination parameters"
        ) from error
    return FollowAssembler.to_following_dto(page)
