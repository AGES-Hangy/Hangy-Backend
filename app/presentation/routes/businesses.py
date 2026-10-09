from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.domain.assemblers import BusinessProfileAssembler
from app.domain.entities import User
from app.domain.services.business_profile import (
    BusinessProfileService,
    NotBusinessProfileError,
)
from app.domain.services.follow import (
    BusinessNotFoundError,
    FollowService,
    TargetNotBusinessError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessProfileRepository,
)
from app.infrastructure.repository.follow import SqlAlchemyFollowRepository
from app.presentation.dtos import BusinessMeOutput
from app.presentation.routes.auth import credentials_exception, get_current_user

router = APIRouter(prefix="/businesses", tags=["Businesses"])


def get_follow_service(db: Annotated[Session, Depends(get_db)]) -> FollowService:
    return FollowService(SqlAlchemyFollowRepository(db))


def get_business_profile_service(
    db: Annotated[Session, Depends(get_db)],
) -> BusinessProfileService:
    return BusinessProfileService(SqlAlchemyBusinessProfileRepository(db))


@router.get(
    "/me",
    response_model=BusinessMeOutput,
    status_code=status.HTTP_200_OK,
    summary="Ver o perfil do estabelecimento autenticado",
    description=(
        "Devolve os dados do perfil comercial do próprio usuário autenticado. "
        "`location` é `null` quando o estabelecimento não tem coordenadas."
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
            "description": "Usuário pessoal chamando o endpoint.",
            "content": {
                "application/json": {"example": {"detail": "Not a business profile"}}
            },
        },
    },
)
def read_current_business_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BusinessProfileService, Depends(get_business_profile_service)],
) -> BusinessMeOutput:
    try:
        profile = service.get_own_profile(current_user)
    except NotBusinessProfileError as error:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Not a business profile"
        ) from error
    return BusinessProfileAssembler.to_dto(profile)


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
