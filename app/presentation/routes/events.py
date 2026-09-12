from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.assemblers import EventAssembler
from app.domain.services import (
    AuthService,
    EventAlreadyFinishedError,
    EventEndsBeforeItStartsError,
    EventNotFoundError,
    EventNotInviteOnlyError,
    EventPrivacyService,
    EventsService,
    EventStartsInThePastError,
    EventTagNotFoundError,
    InvalidAccessTokenError,
    InvalidEventCoordinatesError,
    NotEventOrganizerError,
    TooManyEventTagsError,
)
from app.domain.services.event_privacy import (
    EventNotFoundError as InviteLinkNotFoundError,
)
from app.domain.services.event_privacy import (
    NotEventOrganizerError as NotInviteLinkOrganizerError,
)
from app.domain.services.event_share import (
    EventShareService,
    InviteLinkExpiredError,
    ShareableEventNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.event_invite_link import (
    SqlAlchemyEventInviteLinkRepository,
)
from app.presentation.dtos import (
    CancelEventInput,
    CancelEventOutput,
    CreateEventInput,
    CreateEventOutput,
    CreateInviteLinkOutput,
    EventShareOutput,
    UpdateEventInput,
    UpdateEventOutput,
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


INVITE_LINK_FORBIDDEN_EXAMPLE = {"detail": "Only the organizer can change privacy"}
INVITE_LINK_NOT_FOUND_EXAMPLE = {"detail": "Event not found"}
INVITE_LINK_CONFLICT_EXAMPLE = {"detail": "Event is not invite only"}


def get_events_service(db: Annotated[Session, Depends(get_db)]) -> EventsService:
    return EventsService(repository=SqlAlchemyEventRepository(db))


def get_event_share_service(
    db: Annotated[Session, Depends(get_db)],
) -> EventShareService:
    return EventShareService(repository=SqlAlchemyEventRepository(db))


def get_event_privacy_service(
    db: Annotated[Session, Depends(get_db)],
) -> EventPrivacyService:
    return EventPrivacyService(repository=SqlAlchemyEventInviteLinkRepository(db))


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


@router.get(
    "/{event_id}/share",
    response_model=EventShareOutput,
    status_code=status.HTTP_200_OK,
    summary="Gerar metadados para compartilhar um evento",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou invalido.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento nao pode ser compartilhado.",
        },
        status.HTTP_410_GONE: {
            "description": "O link de convite expirou.",
        },
    },
)
def get_event_share(
    event_id: UUID,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    share_service: Annotated[EventShareService, Depends(get_event_share_service)],
) -> EventShareOutput:
    try:
        auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error

    try:
        share = share_service.get_share(event_id)
    except ShareableEventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except InviteLinkExpiredError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invite link expired",
        ) from error
    return EventAssembler.to_share_dto(share)


@router.post(
    "/{event_id}/invite-link",
    response_model=CreateInviteLinkOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Gerar link de convite do evento",
    description=(
        "Gera um link de convite com token opaco para um evento `INVITE_ONLY`. "
        "So o organizador pode gerar o link, e ele expira no maximo na data de "
        "inicio do evento - um convite nunca sobrevive ao evento."
    ),
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "O usuario autenticado nao e o organizador do evento.",
            "content": {"application/json": {"example": INVITE_LINK_FORBIDDEN_EXAMPLE}},
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento nao existe ou nao esta visivel.",
            "content": {"application/json": {"example": INVITE_LINK_NOT_FOUND_EXAMPLE}},
        },
        status.HTTP_409_CONFLICT: {
            "description": "O evento nao e INVITE_ONLY.",
            "content": {"application/json": {"example": INVITE_LINK_CONFLICT_EXAMPLE}},
        },
    },
)
def create_invite_link(
    event_id: UUID,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    event_privacy_service: Annotated[
        EventPrivacyService, Depends(get_event_privacy_service)
    ],
) -> CreateInviteLinkOutput:
    try:
        organizer = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    if organizer.user_id is None:
        raise credentials_exception

    try:
        invite_link = event_privacy_service.create_invite_link(
            event_id, organizer.user_id
        )
    except InviteLinkNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except NotInviteLinkOrganizerError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer can change privacy",
        ) from error
    except EventNotInviteOnlyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is not invite only",
        ) from error
    return EventAssembler.to_invite_link_dto(invite_link, settings.invite_link_base_url)


@router.patch(
    "/{event_id}",
    response_model=UpdateEventOutput,
    status_code=status.HTTP_200_OK,
    summary="Editar um evento",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "A nova data, horario ou local e invalido.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Apenas o organizador pode editar o evento.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento nao existe ou nao esta visivel.",
        },
        status.HTTP_409_CONFLICT: {
            "description": "Eventos encerrados nao podem ser editados.",
        },
    },
)
def update_event(
    event_id: UUID,
    payload: UpdateEventInput,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    events_service: Annotated[EventsService, Depends(get_events_service)],
) -> UpdateEventOutput:
    try:
        organizer = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    if organizer.user_id is None:
        raise credentials_exception

    try:
        event = events_service.update(
            event_id,
            organizer.user_id,
            EventMapper.to_event_update(payload),
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
    except EventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except NotEventOrganizerError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer can edit this event",
        ) from error
    except EventAlreadyFinishedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event already finished",
        ) from error
    return EventAssembler.to_updated_dto(event)


@router.patch("/{event_id}/cancel", response_model=CancelEventOutput)
def cancel_event(
    event_id: UUID,
    _: CancelEventInput,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    events_service: Annotated[EventsService, Depends(get_events_service)],
) -> CancelEventOutput:
    try:
        requester = auth_service.get_user_from_token(token)
        event = events_service.cancel(event_id, requester.user_id)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    except EventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        ) from error
    except NotEventOrganizerError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer can edit this event",
        ) from error
    except EventAlreadyFinishedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event already finished",
        ) from error
    return EventAssembler.to_cancel_dto(event)
