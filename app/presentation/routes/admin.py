from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import AdminDashboardAssembler, AdminReportAssembler
from app.domain.services import (
    AdminDashboardService,
    AdminReportsService,
    ReportNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.admin_dashboard import (
    SqlAlchemyAdminDashboardRepository,
)
from app.infrastructure.repository.admin_report import (
    SqlAlchemyAdminReportsRepository,
)
from app.presentation.dependencies.admin import require_admin
from app.presentation.dtos import AdminDashboardOutput, AdminReportDetailOutput

router = APIRouter(tags=["Admin"])

__all__ = ["router"]


def get_admin_dashboard_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminDashboardService:
    return AdminDashboardService(repository=SqlAlchemyAdminDashboardRepository(db))


def get_admin_reports_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminReportsService:
    return AdminReportsService(repository=SqlAlchemyAdminReportsRepository(db))


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


@router.get(
    "/admin/reports/{report_id}",
    response_model=AdminReportDetailOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
    summary="Detalhe de uma denúncia",
    description=(
        "Retorna o detalhe completo de uma denúncia: conta responsável pelo alvo "
        "(usuário, estabelecimento ou organizador do evento denunciado), motivo, "
        "relato de quem denunciou, histórico de denúncias anteriores fechadas "
        "contra o mesmo alvo e, quando já resolvida, os dados da resolução. "
        "Exige Bearer token de um usuário com `role = ADMIN`."
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
            "description": "Denúncia não encontrada.",
            "content": {
                "application/json": {"example": {"detail": "Report not found"}}
            },
        },
    },
)
def read_admin_report_detail(
    report_id: UUID,
    reports_service: Annotated[AdminReportsService, Depends(get_admin_reports_service)],
) -> AdminReportDetailOutput:
    try:
        detail = reports_service.get_report_detail(report_id)
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        ) from error
    return AdminReportAssembler.to_detail_dto(detail)
