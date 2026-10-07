from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers.users import UsersAssembler
from app.domain.entities import User
from app.domain.services.users import UserNotFoundError, UsersService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.user_profile import SqlAlchemyUserProfileRepository
from app.presentation.dtos.users import UserProfileDTO
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Users"])


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


__all__ = ["router", "get_user_profile"]
