from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import ExperienceAssembler
from app.domain.entities import User
from app.domain.services.experience import (
    DEFAULT_EVENT_PHOTOS_LIMIT,
    ExperienceAlreadyExistsError,
    ExperienceEventNotFinishedError,
    ExperienceEventNotFoundError,
    ExperienceParticipantNotConfirmedError,
    ExperienceService,
)
from app.domain.services.pagination import InvalidPaginationError
from app.infrastructure.repository import get_db
from app.infrastructure.repository.experience import SqlAlchemyExperienceRepository
from app.presentation.dtos import (
    CreateExperienceInput,
    CreateExperienceOutput,
    EventPhotosOutput,
)
from app.presentation.mappers import ExperienceMapper
from app.presentation.routes.auth import credentials_exception, get_current_user

__all__ = ["get_experience_service", "router"]

router = APIRouter(prefix="/events", tags=["Events"])


def get_experience_service(
    db: Annotated[Session, Depends(get_db)],
) -> ExperienceService:
    return ExperienceService(SqlAlchemyExperienceRepository(db))


@router.post(
    "/{event_id}/experiences",
    response_model=CreateExperienceOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Criar experiência em um evento encerrado",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "O evento ainda não terminou.",
            "content": {
                "application/json": {
                    "example": {"detail": "Event has not finished yet"}
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "O usuário não é participante confirmado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Only confirmed participants can post"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento não existe ou não é visível ao usuário.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
        status.HTTP_409_CONFLICT: {
            "description": "O participante já tem uma experiência neste evento.",
            "content": {
                "application/json": {"example": {"detail": "Experience already exists"}}
            },
        },
    },
)
def create_experience(
    event_id: UUID,
    payload: CreateExperienceInput,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ExperienceService, Depends(get_experience_service)],
) -> CreateExperienceOutput:
    if user.user_id is None:
        raise credentials_exception

    try:
        experience = service.create(
            event_id, user.user_id, ExperienceMapper.to_new_experience(payload)
        )
    except ExperienceEventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except ExperienceParticipantNotConfirmedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only confirmed participants can post",
        ) from error
    except ExperienceEventNotFinishedError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event has not finished yet",
        ) from error
    except ExperienceAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Experience already exists",
        ) from error
    return ExperienceAssembler.to_created_dto(experience, event_id)


@router.get(
    "/{event_id}/photos",
    response_model=EventPhotosOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar as fotos de um evento",
    description=(
        "Lista as fotos publicadas pelos participantes nas experiências do "
        "evento, da mais recente para a mais antiga. `can_delete` indica se o "
        "usuário autenticado pode remover aquela foto (ele é o autor ou o "
        "organizador do evento). Fotos e experiências excluídas, e fotos de "
        "contas excluídas, não aparecem. `photo_url` é devolvida como está "
        "gravada. Paginação por cursor opaco (`next_cursor`)."
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
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento não existe ou não é visível ao usuário.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
    },
)
def read_event_photos(
    event_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ExperienceService, Depends(get_experience_service)],
    limit: Annotated[
        int, Query(description="Tamanho da página (1–100).")
    ] = DEFAULT_EVENT_PHOTOS_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação.")
    ] = None,
) -> EventPhotosOutput:
    if user.user_id is None:
        raise credentials_exception

    try:
        page = service.list_photos(event_id, user.user_id, limit=limit, cursor=cursor)
    except ExperienceEventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    return ExperienceAssembler.to_photos_dto(page)
