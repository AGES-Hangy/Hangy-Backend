from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from starlette.concurrency import run_in_threadpool

from app.domain.assemblers import ExperienceAssembler
from app.domain.entities import User
from app.domain.services import (
    ImageStorageUnavailableError,
    ImageTooLargeError,
    UnsupportedImageTypeError,
)
from app.domain.services.experience import (
    ExperienceNotFoundError,
    ExperienceParticipantNotConfirmedError,
    ExperiencePhotoDeleteForbiddenError,
    ExperiencePhotoLimitReachedError,
    ExperiencePhotoNotFoundError,
    ExperienceService,
)
from app.presentation.dependencies.auth import credentials_exception, get_current_user
from app.presentation.dtos import (
    CreateExperienceOutput,
    ExperienceImageOutput,
    UpdateExperienceInput,
)
from app.presentation.mappers import read_image_upload
from app.presentation.routes.experiences import get_experience_service

__all__ = ["router"]

router = APIRouter(prefix="/experiences", tags=["Experiences"])


@router.patch(
    "/{experience_id}",
    response_model=CreateExperienceOutput,
    status_code=status.HTTP_200_OK,
    summary="Editar a descrição da experiência",
    description=(
        "Troca a descrição da experiência do usuário autenticado. Só o autor "
        "edita; as fotos não mudam e voltam na resposta."
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
        status.HTTP_404_NOT_FOUND: {
            "description": "A experiência não existe ou é de outro usuário.",
            "content": {
                "application/json": {"example": {"detail": "Experience not found"}}
            },
        },
    },
)
def update_experience(
    experience_id: UUID,
    payload: UpdateExperienceInput,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ExperienceService, Depends(get_experience_service)],
) -> CreateExperienceOutput:
    if user.user_id is None:
        raise credentials_exception

    try:
        details = service.update_description(
            experience_id, user.user_id, payload.description
        )
    except ExperienceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Experience not found"
        ) from error
    return ExperienceAssembler.to_details_dto(details)


@router.post(
    "/{experience_id}/images",
    response_model=ExperienceImageOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Adicionar uma foto à experiência",
    description=(
        "Recebe um JPG ou PNG de até 5 MB em `multipart/form-data` (campo "
        "`file`), grava no S3 e anexa à experiência do usuário autenticado. "
        "A `photo_url` é gerada pelo servidor. Cada usuário pode manter um "
        "número limitado de fotos por evento (fotos removidas não contam)."
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
            "description": "O usuário não é mais participante confirmado do evento.",
            "content": {
                "application/json": {
                    "example": {"detail": "Only confirmed participants can post"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "A experiência não existe ou é de outro usuário.",
            "content": {
                "application/json": {"example": {"detail": "Experience not found"}}
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Limite de fotos por usuário neste evento atingido.",
            "content": {
                "application/json": {"example": {"detail": "Photo limit reached"}}
            },
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "description": "Arquivo acima do limite de tamanho.",
            "content": {"application/json": {"example": {"detail": "Image too large"}}},
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "description": "Arquivo vazio ou conteúdo diferente de JPG/PNG.",
            "content": {
                "application/json": {"example": {"detail": "Unsupported image type"}}
            },
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Storage não configurado ou indisponível.",
            "content": {
                "application/json": {"example": {"detail": "Image storage unavailable"}}
            },
        },
    },
)
async def upload_experience_image(
    experience_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ExperienceService, Depends(get_experience_service)],
    file: Annotated[UploadFile, File()],
) -> ExperienceImageOutput:
    if user.user_id is None:
        raise credentials_exception

    try:
        content = await read_image_upload(
            file, service.image_upload_service.max_size_bytes
        )
        image = await run_in_threadpool(
            service.add_photo,
            experience_id,
            user.user_id,
            content,
            file.content_type or "",
        )
    except ExperienceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Experience not found"
        ) from error
    except ExperienceParticipantNotConfirmedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only confirmed participants can post",
        ) from error
    except ExperiencePhotoLimitReachedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Photo limit reached"
        ) from error
    except ImageTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image too large"
        ) from error
    except UnsupportedImageTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type",
        ) from error
    except ImageStorageUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage unavailable",
        ) from error
    return ExperienceAssembler.to_image_dto(image)


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
