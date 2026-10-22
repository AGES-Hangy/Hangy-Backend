from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.domain.services import (
    ImageStorage,
    ImageStorageUnavailableError,
    ImageTooLargeError,
    ImageUploadService,
    UnsupportedImageTypeError,
)
from app.infrastructure.storage import get_image_storage
from app.presentation.dtos import EventCoverUploadOutput
from app.presentation.mappers import read_image_upload
from app.presentation.routes.auth import get_current_user

__all__ = ["get_image_upload_service", "router", "upload_event_cover"]

router = APIRouter(prefix="/uploads", tags=["Uploads"])


def get_image_upload_service(
    storage: Annotated[ImageStorage, Depends(get_image_storage)],
) -> ImageUploadService:
    return ImageUploadService(storage)


@router.post(
    "/event-covers",
    response_model=EventCoverUploadOutput,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_user)],
    summary="Enviar a capa de um evento",
    description=(
        "Recebe um JPG ou PNG de ate 5 MB. Use a cover_photo_url retornada "
        "no POST /events ou PATCH /events/{event_id}."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou invalido.",
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
            "description": "Arquivo vazio ou conteudo diferente de JPG/PNG.",
            "content": {
                "application/json": {"example": {"detail": "Unsupported image type"}}
            },
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Storage nao configurado ou indisponivel.",
            "content": {
                "application/json": {"example": {"detail": "Image storage unavailable"}}
            },
        },
    },
)
async def upload_event_cover(
    image_upload_service: Annotated[
        ImageUploadService, Depends(get_image_upload_service)
    ],
    file: Annotated[UploadFile, File()],
) -> EventCoverUploadOutput:
    try:
        content = await read_image_upload(file, image_upload_service.max_size_bytes)
        url = await run_in_threadpool(
            image_upload_service.upload,
            folder="events/covers",
            content=content,
            content_type=file.content_type or "",
        )
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
    return EventCoverUploadOutput(cover_photo_url=url)
