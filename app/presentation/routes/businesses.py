from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.services.follow import (
    BusinessNotFoundError,
    FollowService,
    TargetNotBusinessError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.follow import SqlAlchemyFollowRepository
from app.presentation.routes.auth import credentials_exception, get_current_user

router = APIRouter(prefix="/businesses", tags=["Businesses"])


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
