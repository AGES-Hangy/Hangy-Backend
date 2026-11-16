from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import AdminEventsAssembler
from app.domain.services import AdminEventNotFoundError, AdminEventsService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.admin_events import SqlAlchemyAdminEventsRepository
from app.presentation.dependencies.admin import require_admin
from app.presentation.dtos import AdminEventDetailOutput

router = APIRouter(tags=["Admin"])


def get_admin_events_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminEventsService:
    return AdminEventsService(repository=SqlAlchemyAdminEventsRepository(db))


@router.get(
    "/admin/events/{event_id}",
    response_model=AdminEventDetailOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
    summary="Ficha de moderação de um evento",
    description=(
        "Devolve o evento como o organizador o cadastrou, sem as regras de "
        "visibilidade do app: local exato (`latitude`/`longitude`) mesmo em "
        "evento privado, `status` do evento e `moderation_status` "
        "(`REMOVED` depois de `PATCH /admin/events/{event_id}/moderation`). "
        "Um evento removido continua com ficha. `organizer` traz o status de "
        "moderação da conta e as contagens da ficha dela. Em `metrics`, "
        "`participant_count` conta as participações confirmadas e "
        "`pending_count` as solicitações pendentes; `report_count` ignora "
        "denúncias arquivadas e `report_upheld_count` conta as que terminaram "
        "com o evento removido. Exige Bearer token de um usuário com "
        "`role = ADMIN`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Usuário autenticado, mas `role != ADMIN`.",
            "content": {
                "application/json": {"example": {"detail": "Admin access required"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O `event_id` não existe.",
            "content": {"application/json": {"example": {"detail": "Event not found"}}},
        },
    },
)
def read_admin_event_detail(
    event_id: UUID,
    admin_events_service: Annotated[
        AdminEventsService, Depends(get_admin_events_service)
    ],
) -> AdminEventDetailOutput:
    try:
        detail = admin_events_service.get_event_detail(event_id)
    except AdminEventNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from error
    return AdminEventsAssembler.to_detail_dto(detail)
