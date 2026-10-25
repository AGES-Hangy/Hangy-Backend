from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.domain.entities import User
from app.domain.services.experience import (
    ExperiencePhotoDeleteForbiddenError,
    ExperiencePhotoNotFoundError,
    ExperienceService,
)
from app.presentation.routes.auth import get_current_user
from app.presentation.routes.experiences import get_experience_service

__all__ = ["router"]

router = APIRouter(prefix="/experiences", tags=["Experiences"])


@router.delete(
    "/images/{photo_id}",
    response_model=None,
    response_class=Response,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover uma foto da galeria do evento",
    description=(
        "Remove a foto da galeria (`deleted_at`) e apaga o arquivo no S3. Só o "
        "autor da foto ou o organizador do evento podem removê-la. Falha ao "
        "apagar o arquivo no S3 não derruba a requisição: é registrada em log "
        "e a resposta continua sendo 204."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "O usuário não é o autor da foto nem o organizador.",
            "content": {
                "application/json": {
                    "example": {"detail": "Only the author or the organizer can delete"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "A foto não existe ou já foi removida.",
            "content": {"application/json": {"example": {"detail": "Photo not found"}}},
        },
    },
)
def delete_experience_image(
    photo_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ExperienceService, Depends(get_experience_service)],
) -> Response:
    try:
        service.delete_photo(photo_id, user.user_id)
    except ExperiencePhotoNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found",
        ) from error
    except ExperiencePhotoDeleteForbiddenError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author or the organizer can delete",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
