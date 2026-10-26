from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.domain.entities import User
from app.domain.services import (
    ImageStorageUnavailableError,
    ImageTooLargeError,
    ImageUploadService,
    UnsupportedImageTypeError,
)
from app.domain.services.profile_photo import (
    ProfilePhotoService,
    ProfilePhotoUserNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.dtos import ProfilePhotoOutput
from app.presentation.mappers import read_image_upload
from app.presentation.routes.auth import credentials_exception, get_current_user
from app.presentation.routes.uploads import get_image_upload_service

__all__ = ["router"]

router = APIRouter(tags=["Profile"])


def get_profile_photo_service(
    db: Annotated[Session, Depends(get_db)],
    image_upload_service: Annotated[
        ImageUploadService, Depends(get_image_upload_service)
    ],
) -> ProfilePhotoService:
    return ProfilePhotoService(SqlAlchemyUserRepository(db), image_upload_service)


@router.post(
    "/users/me/photo",
    response_model=ProfilePhotoOutput,
    status_code=status.HTTP_200_OK,
    summary="Trocar a foto de perfil",
    description=(
        "Recebe um JPG ou PNG de até 5 MB em `multipart/form-data` (campo "
        "`file`), grava no S3 e passa a ser a foto do usuário autenticado — "
        "pessoa física ou estabelecimento. A foto anterior é apagada do S3."
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
async def upload_profile_photo(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProfilePhotoService, Depends(get_profile_photo_service)],
    file: Annotated[UploadFile, File()],
) -> ProfilePhotoOutput:
    if user.user_id is None:
        raise credentials_exception

    try:
        content = await read_image_upload(
            file, service.image_upload_service.max_size_bytes
        )
        photo_url = await run_in_threadpool(
            service.replace, user.user_id, content, file.content_type or ""
        )
    except ProfilePhotoUserNotFoundError as error:
        raise credentials_exception from error
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
    return ProfilePhotoOutput(photo_url=photo_url)
