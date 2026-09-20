from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import InviteAssembler
from app.domain.services import (
    AuthService,
    InvalidAccessTokenError,
    InviteAlreadyAcceptedError,
    InviteEventFullError,
    InviteEventNotFoundError,
    InviteLinkExpiredError,
    InviteLinkNotFoundError,
    InviteService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.invite import SqlAlchemyInviteRepository
from app.presentation.dtos import AcceptInviteOutput
from app.presentation.routes.auth import (
    credentials_exception,
    get_access_token,
    get_auth_service,
)

router = APIRouter(prefix="/invites", tags=["Invites"])


def get_invite_service(db: Annotated[Session, Depends(get_db)]) -> InviteService:
    return InviteService(repository=SqlAlchemyInviteRepository(db))


@router.post(
    "/{token}/accept",
    response_model=AcceptInviteOutput,
    status_code=status.HTTP_200_OK,
    summary="Aceitar convite por link",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou invalido.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O convite ou o evento nao existe.",
        },
        status.HTTP_409_CONFLICT: {
            "description": "O usuario ja participa do evento ou ele esta lotado.",
        },
        status.HTTP_410_GONE: {"description": "O link de convite expirou."},
    },
)
def accept_invite(
    token: str,
    access_token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    invite_service: Annotated[InviteService, Depends(get_invite_service)],
) -> AcceptInviteOutput:
    try:
        user = auth_service.get_user_from_token(access_token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error

    try:
        participant = invite_service.accept(token, user.user_id)
    except InviteLinkNotFoundError as error:
        raise HTTPException(status_code=404, detail="Invite link not found") from error
    except InviteEventNotFoundError as error:
        raise HTTPException(status_code=404, detail="Event not found") from error
    except InviteLinkExpiredError as error:
        raise HTTPException(status_code=410, detail="Invite link expired") from error
    except InviteEventFullError as error:
        raise HTTPException(status_code=409, detail="Event is full") from error
    except InviteAlreadyAcceptedError as error:
        raise HTTPException(
            status_code=409, detail="Invite already accepted"
        ) from error
    return InviteAssembler.to_accepted_dto(participant)
