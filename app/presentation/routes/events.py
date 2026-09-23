from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.assemblers import (
    EventAssembler,
    EventDetailsAssembler,
    EventParticipantsAssembler,
    EventParticipationAssembler,
)
from app.domain.services import (
    AuthService,
    EventAlreadyFinishedError,
    EventCancelledError,
    EventDetailsNotFoundError,
    EventDetailsService,
    EventEndsBeforeItStartsError,
    EventIsFullError,
    EventNotFoundError,
    EventNotInviteOnlyError,
    EventParticipantNotFoundError,
    EventPrivacyService,
    EventsService,
    EventStartsInThePastError,
    EventTagNotFoundError,
    InvalidAccessTokenError,
    InvalidEventCoordinatesError,
    InvalidParticipantStatusTransitionError,
    NotEventOrganizerError,
    TooManyEventTagsError,
)
from app.domain.services.event_participant import (
    DEFAULT_PARTICIPANTS_LIMIT,
    EventParticipantsService,
    InvalidParticipantStatusError,
)
from app.domain.services.event_participant import (
    EventNotFoundError as EventParticipantsNotFoundError,
)
from app.domain.services.event_participant import (
    NotEventOrganizerError as NotEventOrganizerForParticipantsError,
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
from app.domain.services.participation import (
    AlreadyParticipatingError,
    InviteOnlyEventError,
    OrganizerCannotJoinError,
    ParticipationService,
    RequestAlreadyPendingError,
)
from app.domain.services.participation import (
    EventAlreadyFinishedError as ParticipationAlreadyFinishedError,
)
from app.domain.services.participation import (
    EventIsFullError as ParticipationIsFullError,
)
from app.domain.services.participation import (
    EventNotFoundError as ParticipationEventNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.event_details import SqlAlchemyEventDetailsRepository
from app.infrastructure.repository.event_invite_link import (
    SqlAlchemyEventInviteLinkRepository,
)
from app.infrastructure.repository.event_participant import (
    SqlAlchemyEventParticipantsRepository,
)
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.infrastructure.repository.participation import (
    SqlAlchemyParticipationRepository,
)
from app.presentation.dtos import (
    CancelEventInput,
    CancelEventOutput,
    CreateEventInput,
    CreateEventOutput,
    CreateInviteLinkOutput,
    EventDetailsOutput,
    EventParticipantsOutput,
    EventParticipationOutput,
    EventShareOutput,
    UpdateEventInput,
    UpdateEventOutput,
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


INVITE_LINK_FORBIDDEN_EXAMPLE = {"detail": "Only the organizer can change privacy"}
INVITE_LINK_NOT_FOUND_EXAMPLE = {"detail": "Event not found"}
INVITE_LINK_CONFLICT_EXAMPLE = {"detail": "Event is not invite only"}


def get_events_service(db: Annotated[Session, Depends(get_db)]) -> EventsService:
    return EventsService(
        repository=SqlAlchemyEventRepository(db, SqlAlchemyNotificationRepository(db))
    )


def get_event_details_service(
    db: Annotated[Session, Depends(get_db)],
) -> EventDetailsService:
    return EventDetailsService(repository=SqlAlchemyEventDetailsRepository(db))


def get_event_share_service(
    db: Annotated[Session, Depends(get_db)],
) -> EventShareService:
    return EventShareService(
        repository=SqlAlchemyEventRepository(db, SqlAlchemyNotificationRepository(db)),
        frontend_base_url=settings.frontend_base_url,
    )


def get_event_privacy_service(
    db: Annotated[Session, Depends(get_db)],
) -> EventPrivacyService:
    return EventPrivacyService(repository=SqlAlchemyEventInviteLinkRepository(db))


def get_event_participants_service(
    db: Annotated[Session, Depends(get_db)],
) -> EventParticipantsService:
    return EventParticipantsService(
        repository=SqlAlchemyEventParticipantsRepository(db)
    )


def get_participation_service(
    db: Annotated[Session, Depends(get_db)],
) -> ParticipationService:
    return ParticipationService(
        repository=SqlAlchemyParticipationRepository(
            db, SqlAlchemyNotificationRepository(db)
        )
    )


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
    "/{event_id}",
    response_model=EventDetailsOutput,
    status_code=status.HTTP_200_OK,
    summary="Ver detalhes de um evento",
    description=(
        "Resolve a visibilidade e a acao disponivel para o usuario autenticado. "
        "Eventos por convite e bloqueios usam 404 para nao revelar o evento."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou invalido.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento nao existe ou nao esta visivel.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
        status.HTTP_410_GONE: {
            "description": "O evento foi cancelado.",
            "content": {
                "application/json": {"example": {"detail": "Event was cancelled"}}
            },
        },
    },
)
def get_event_details(
    event_id: UUID,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    details_service: Annotated[EventDetailsService, Depends(get_event_details_service)],
) -> EventDetailsOutput:
    try:
        viewer = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    if viewer.user_id is None:
        raise credentials_exception

    try:
        details = details_service.get_details(event_id, viewer.user_id)
    except EventDetailsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except EventCancelledError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Event was cancelled",
        ) from error
    return EventDetailsAssembler.to_dto(details)


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


@router.post(
    "/{event_id}/participation",
    response_model=EventParticipationOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Confirmar presenca ou solicitar entrada em um evento",
    description=(
        "Cria ou atualiza a participacao do usuario autenticado no evento. A "
        "decisao entre confirmacao direta e solicitacao pendente e 100% do "
        "backend, com base em `event.event_privacy` - o cliente sempre chama "
        "este mesmo endpoint e le o campo `status` da resposta para saber o "
        "que aconteceu. Eventos `INVITE_ONLY` nao sao atendidos aqui (usam "
        "`POST /invites/{token}/accept`)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente, expirado ou invalido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Evento e INVITE_ONLY; este endpoint nao o atende.",
            "content": {
                "application/json": {"example": {"detail": "Event is invite-only"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Evento inexistente ou nao visivel.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
        status.HTTP_409_CONFLICT: {
            "description": (
                "Evento lotado, ja encerrado, ou ja existe uma solicitacao em "
                "aberto para este evento."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "full": {
                            "summary": "Lotacao atingida",
                            "value": {"detail": "Event is full"},
                        },
                        "finished": {
                            "summary": "Evento encerrado",
                            "value": {"detail": "Event already finished"},
                        },
                        "pending": {
                            "summary": "Solicitacao ja em aberto",
                            "value": {"detail": "Request already pending"},
                        },
                    }
                }
            },
        },
    },
)
def create_event_participation(
    event_id: UUID,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    participation_service: Annotated[
        ParticipationService, Depends(get_participation_service)
    ],
) -> EventParticipationOutput:
    try:
        user = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    if user.user_id is None:
        raise credentials_exception

    try:
        participant = participation_service.request_or_join(event_id, user.user_id)
    except ParticipationEventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    except InviteOnlyEventError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event is invite-only",
        ) from error
    except ParticipationAlreadyFinishedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event already finished",
        ) from error
    except ParticipationIsFullError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is full",
        ) from error
    except RequestAlreadyPendingError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request already pending",
        ) from error
    except AlreadyParticipatingError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already participating in this event",
        ) from error
    except OrganizerCannotJoinError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event creator cannot join their own event",
        ) from error
    return EventParticipationAssembler.to_dto(participant)


@router.get(
    "/{event_id}/participants",
    response_model=EventParticipantsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar participantes do evento",
    description=(
        "Sem filtro devolve os participantes confirmados, visiveis conforme a "
        "privacidade do evento. So o organizador pode pedir `status=PENDING`. "
        "Os contadores vem agregados na mesma resposta; o contador de PENDING "
        "so aparece para o organizador."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou invalido.",
        },
        status.HTTP_400_BAD_REQUEST: {
            "description": "O status informado nao e PENDING nem CONFIRMED.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid participant status"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "So o organizador pode listar participantes pendentes.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Only the organizer can list pending participants"
                    }
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O evento nao existe ou nao esta visivel.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
    },
)
def get_event_participants(
    event_id: UUID,
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    participants_service: Annotated[
        EventParticipantsService, Depends(get_event_participants_service)
    ],
    participant_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="PENDING ou CONFIRMED. Sem filtro, traz os confirmados.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_PARTICIPANTS_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> EventParticipantsOutput:
    try:
        viewer = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    if viewer.user_id is None:
        raise credentials_exception

    try:
        page = participants_service.list_participants(
            event_id=event_id,
            viewer_id=viewer.user_id,
            status=participant_status,
            limit=limit,
            cursor=cursor,
        )
    except EventParticipantsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        ) from error
    except InvalidParticipantStatusError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid participant status",
        ) from error
    except NotEventOrganizerForParticipantsError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer can list pending participants",
        ) from error
    return EventParticipantsAssembler.to_dto(page)


@router.patch(
    "/{event_id}/participants/{participant_id}",
    response_model=UpdateEventParticipantOutput,
    status_code=status.HTTP_200_OK,
    summary="Aprovar, recusar ou remover um participante",
    description=(
        "Permite ao organizador do evento atualizar o status de um participante "
        "respeitando a maquina de estados: PENDING -> CONFIRMED|REJECTED, "
        "CONFIRMED -> REMOVED. Aprovacoes respeitam o limite maximo de "
        "participantes (max_participants). Todas as alteracoes notificam o "
        "participante."
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
                    "example": {"detail": "Only the organizer can manage participants"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Participante ou evento não encontrado.",
            "content": {
                "application/json": {"example": {"detail": "Participant not found"}}
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
            detail="Participant not found",
        ) from error
    except NotEventOrganizerError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organizer can manage participants",
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
