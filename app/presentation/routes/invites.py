from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.assemblers import EventAssembler
from app.domain.services.event_share import (
    EventShareService,
    InviteLinkExpiredError,
    ShareableEventNotFoundError,
)
from app.presentation.dtos import EventInvitePreviewOutput
from app.presentation.routes.events import get_event_share_service

router = APIRouter(prefix="/invites", tags=["Invites"])


@router.get(
    "/{token}",
    response_model=EventInvitePreviewOutput,
    status_code=status.HTTP_200_OK,
    summary="Resolver um link de convite",
    description=(
        "Endpoint publico que resolve o token de um convite para o evento "
        "correspondente - e o que faz o deep link funcionar antes do login."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "O token nao existe ou o evento foi cancelado.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
        status.HTTP_410_GONE: {
            "description": "O link de convite expirou.",
            "content": {
                "application/json": {"example": {"detail": "Invite link expired"}}
            },
        },
    },
)
def get_invite(
    token: str,
    share_service: Annotated[EventShareService, Depends(get_event_share_service)],
) -> EventInvitePreviewOutput:
    try:
        event = share_service.resolve_invite(token)
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
    return EventAssembler.to_invite_preview_dto(event)
