from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import EventAssembler
from app.domain.services import (
    AuthService,
    EventEndsBeforeItStartsError,
    EventIsFullError,
    EventNotFoundError,
    EventParticipantNotFoundError,
    EventsService,
    EventStartsInThePastError,
    EventTagNotFoundError,
    InvalidAccessTokenError,
    InvalidEventCoordinatesError,
    InvalidParticipantStatusTransitionError,
    NotEventOrganizerError,
    TooManyEventTagsError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.presentation.dtos import (
    CreateEventInput,
    CreateEventOutput,
    UpdateEventParticipantInput,
    UpdateEventParticipantOutput,
)
from app.presentation.mappers import EventMapper
from app.presentation.routes.auth import (
    credentials_exception,
    get_access_token,
    get_auth_service,
)

router = APIRouter(prefix="/events", tags=["Events"])

BAD_REQUEST_EXAMPLES = {
    "past_date": {
        "summary": "Data no passado",
        "value": {"detail": "Event date must be in the future"},
    },
    "end_before_start": {
        "summary": "Termino antes do inicio",
        "value": {"detail": "Event must end after it starts"},
    },
    "too_many_tags": {
        "summary": "Mais de 5 tags",
        "value": {"detail": "An event accepts at most 5 tags"},
    },
    "invalid_coordinates": {
        "summary": "Coordenadas fora de faixa",
        "value": {"detail": "Invalid event coordinates"},
    },
}


def get_events_service(db: Annotated[Session, Depends(get_db)]) -> EventsService:
    return EventsService(repository=SqlAlchemyEventRepository(db))


@router.post(
    "",
    response_model=CreateEventOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Criar e publicar um evento",
    description=(
        "O usuario autenticado vira o organizador. O evento nasce com status "
        "`PUBLISHED`: o fluxo do app publica direto, sem rascunho. `event_date` "
        "precisa estar no futuro, `end_date` precisa ser posterior a ela e o "
        "evento aceita no maximo 5 tags. Sem `max_participants` o evento nao "
        "tem limite de lotacao."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Alguma regra de negocio do evento foi violada.",
            "content": {"application/json": {"examples": BAD_REQUEST_EXAMPLES}},
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Alguma das tags informadas nao existe.",
            "content": {"application/json": {"example": {"detail": "Tag not found"}}},
        },
    },
)
def create_event(
    payload: CreateEventInput,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    events_service: Annotated[EventsService, Depends(get_events_service)],
) -> CreateEventOutput:
    try:
        organizer = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error

    try:
        event = events_service.create(
            EventMapper.to_new_event(payload, organizer.user_id)
        )
    except EventStartsInThePastError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event date must be in the future",
        ) from error
    except EventEndsBeforeItStartsError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event must end after it starts",
        ) from error
    except InvalidEventCoordinatesError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid event coordinates",
        ) from error
    except TooManyEventTagsError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An event accepts at most 5 tags",
        ) from error
    except EventTagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        ) from error
    return EventAssembler.to_created_dto(event, organizer)


@router.patch(
    "/{event_id}/participants/{participant_id}",
    response_model=UpdateEventParticipantOutput,
    status_code=status.HTTP_200_OK,
    summary="Aprovar, recusar ou remover um participante",
    description=(
        "Permite ao organizador do evento atualizar o status de um participante "
        "respeitando a maquina de estados: PENDING -> CONFIRMED|REJECTED, "
        "CONFIRMED -> REMOVED, INVITED -> CONFIRMED|REJECTED. Aprovacoes "
        "respeitam o limite maximo de participantes (max_participants). Todas "
        "as alteracoes notificam o participante."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Transição de status inválida para o participante.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid participant status transition"}
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Usuário autenticado não é o organizador do evento.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Only the event organizer can manage participants"
                    }
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Evento ou participante não encontrado.",
            "content": {
                "application/json": {
                    "examples": {
                        "event_not_found": {
                            "summary": "Evento não encontrado",
                            "value": {"detail": "Event not found"},
                        },
                        "participant_not_found": {
                            "summary": "Participante não encontrado",
                            "value": {"detail": "Participant not found"},
                        },
                    }
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "O evento atingiu o limite máximo de participantes.",
            "content": {"application/json": {"example": {"detail": "Event is full"}}},
        },
    },
)
def update_event_participant(
    event_id: UUID,
    participant_id: UUID,
    payload: UpdateEventParticipantInput,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    events_service: Annotated[EventsService, Depends(get_events_service)],
) -> UpdateEventParticipantOutput:
    try:
        user = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error

    try:
        participant = events_service.update_participant_status(
            event_id=event_id,
            participant_id=participant_id,
            new_status=payload.status,
            requester_id=user.user_id,
        )
    except EventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except NotEventOrganizerError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the event organizer can manage participants",
        ) from error
    except EventParticipantNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Participant not found",
        ) from error
    except InvalidParticipantStatusTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid participant status transition",
        ) from error
    except EventIsFullError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is full",
        ) from error

    return EventAssembler.to_participant_updated_dto(participant)
