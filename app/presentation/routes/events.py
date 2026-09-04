from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import EventAssembler
from app.domain.services import (
    AuthService,
    EventAlreadyFinishedError,
    EventNotFoundError,
    EventsService,
    InvalidAccessTokenError,
    NotEventOrganizerError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.presentation.dtos import CancelEventInput, CancelEventOutput
from app.presentation.routes.auth import (
    credentials_exception,
    get_access_token,
    get_auth_service,
)

router = APIRouter(prefix="/events", tags=["Events"])


def get_events_service(db: Annotated[Session, Depends(get_db)]) -> EventsService:
    return EventsService(repository=SqlAlchemyEventRepository(db))


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
