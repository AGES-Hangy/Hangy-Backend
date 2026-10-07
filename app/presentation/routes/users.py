from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.domain.entities import User
from app.domain.services import (
    BlockedUserNotFoundError,
    BlockService,
    CannotBlockSelfError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.block import SqlAlchemyBlockRepository
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Users"])


def get_block_service(db: Annotated[Session, Depends(get_db)]) -> BlockService:
    return BlockService(
        repository=SqlAlchemyBlockRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
    )


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
