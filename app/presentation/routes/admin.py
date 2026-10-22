from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.domain.assemblers import AdminDashboardAssembler
from app.domain.services import AdminDashboardService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.admin_dashboard import (
    SqlAlchemyAdminDashboardRepository,
)
from app.presentation.dependencies.admin import require_admin
from app.presentation.dtos import AdminDashboardOutput

router = APIRouter(tags=["Admin"])


def get_admin_dashboard_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminDashboardService:
    return AdminDashboardService(repository=SqlAlchemyAdminDashboardRepository(db))


@router.get(
    "/admin/dashboard",
    response_model=AdminDashboardOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
    summary="Métricas do painel administrativo",
    description=(
        "Retorna as contagens de denúncias abertas (`PENDING`) e em análise "
        "(`REVIEWED`), de usuários ativos e de contas suspensas, mais as 5 "
        "denúncias `PENDING`/`REVIEWED` mais recentes. Exige Bearer token de "
        "um usuário com `role = ADMIN`."
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
    },
)
def read_admin_dashboard(
    dashboard_service: Annotated[
        AdminDashboardService, Depends(get_admin_dashboard_service)
    ],
) -> AdminDashboardOutput:
    dashboard = dashboard_service.get_dashboard()
    return AdminDashboardAssembler.to_dto(dashboard)