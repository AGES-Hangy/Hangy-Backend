from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import EventAssembler
from app.domain.services import (
    AuthService,
    EventEndsBeforeItStartsError,
    EventsService,
    EventStartsInThePastError,
    EventTagNotFoundError,
    InvalidAccessTokenError,
    InvalidEventCoordinatesError,
    TooManyEventTagsError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.presentation.dtos import CreateEventInput, CreateEventOutput
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
