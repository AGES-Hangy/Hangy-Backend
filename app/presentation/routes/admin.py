from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import (
    AdminDashboardAssembler,
    AdminReportAssembler,
    AdminUserModerationAssembler,
    TagAssembler,
)
from app.domain.entities import User
from app.domain.services import (
    AccountAlreadyBannedError,
    AccountNotModeratedError,
    AdminDashboardService,
    AdminReportsService,
    AdminTagsService,
    AdminUserModerationService,
    ModeratedUserNotFoundError,
    ParentTagNotCategoryError,
    ParentTagNotFoundError,
    ReportAlreadyResolvedError,
    ReportNotAboutUserError,
    ReportNotFoundError,
    SelfModerationError,
    TagNameAlreadyExistsError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.admin_dashboard import (
    SqlAlchemyAdminDashboardRepository,
)
from app.infrastructure.repository.admin_report import (
    SqlAlchemyAdminReportsRepository,
)
from app.infrastructure.repository.audit import SqlAlchemyAuditRepository
from app.infrastructure.repository.report import SqlAlchemyReportRepository
from app.infrastructure.repository.tag import SqlAlchemyTagRepository
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.dependencies.admin import require_admin
from app.presentation.dtos import (
    AdminDashboardOutput,
    AdminReportDetailOutput,
    AdminTagOutput,
    AdminUserModerationInput,
    AdminUserModerationOutput,
    CreateAdminTagInput,
)
from app.presentation.mappers import AdminTagMapper, AdminUserModerationMapper

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


def get_admin_tags_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminTagsService:
    return AdminTagsService(
        repository=SqlAlchemyTagRepository(db),
        audit_repository=SqlAlchemyAuditRepository(db),
    )


def get_admin_user_moderation_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminUserModerationService:
    return AdminUserModerationService(
        user_repository=SqlAlchemyUserRepository(db),
        report_repository=SqlAlchemyReportRepository(db),
        audit_repository=SqlAlchemyAuditRepository(db),
    )


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


@router.post(
    "/admin/tags",
    response_model=AdminTagOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Criar uma tag",
    description=(
        "Cria uma tag micro dentro de uma categoria existente (`parent_id` com "
        "o id da categoria) ou uma categoria nova, macro (`parent_id: null`). "
        "O nome e unico por nivel: entre as categorias, ou dentro da mesma "
        "categoria. Registra o evento de auditoria `TAG_CREATED` com o admin e a "
        "data. Exige Bearer token de um usuario com `role = ADMIN`."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`parent_id` aponta para uma tag micro, nao uma macro.",
            "content": {
                "application/json": {
                    "example": {"detail": "Parent tag is not a category"}
                }
            },
        },
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
            "description": "O `parent_id` informado nao existe.",
            "content": {
                "application/json": {"example": {"detail": "Parent tag not found"}}
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Ja existe uma tag com esse nome no mesmo nivel.",
            "content": {
                "application/json": {
                    "example": {"detail": "Tag name already exists at this level"}
                }
            },
        },
    },
)
def create_admin_tag(
    payload: CreateAdminTagInput,
    current_admin: Annotated[User, Depends(require_admin)],
    admin_tags_service: Annotated[AdminTagsService, Depends(get_admin_tags_service)],
) -> AdminTagOutput:
    tag = AdminTagMapper.to_entity(payload)
    try:
        created = admin_tags_service.create_tag(tag, actor_id=current_admin.user_id)
    except ParentTagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent tag not found",
        ) from error
    except ParentTagNotCategoryError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent tag is not a category",
        ) from error
    except TagNameAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tag name already exists at this level",
        ) from error
    return TagAssembler.to_admin_dto(created)


@router.patch(
    "/admin/users/{user_id}/moderation",
    response_model=AdminUserModerationOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
    summary="Banir, suspender ou reverter a moderação de uma conta",
    description=(
        "Ponto único de escrita para toda ação de moderação sobre uma conta: "
        "`BAN` (definitivo), `SUSPEND` (até `duration_days` dias) ou `REVERT` "
        "(remove o banimento/suspensão e devolve o acesso imediatamente). "
        "`report_id` é opcional em `BAN`/`SUSPEND` e, quando informado, marca "
        "aquela denúncia como `RESOLVED` na mesma transação. Gera sempre uma "
        "linha de auditoria. Exige Bearer token de um usuário com "
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
            "description": "O `user_id` ou o `report_id` informado não existe.",
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
        status.HTTP_409_CONFLICT: {
            "description": (
                "`SUSPEND` numa conta já banida (`Account is already banned`), "
                "`REVERT` numa conta já ativa (`User is not banned or "
                "suspended`), `report_id` de uma denúncia já `RESOLVED`/"
                "`REJECTED` (`Report already resolved`) ou que não denuncia "
                "este usuário (`Report is not about this user`), ou admin "
                "moderando a própria conta (`Admins cannot moderate their own "
                "account`)."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "User is not banned or suspended"}
                }
            },
        },
    },
)
def patch_admin_user_moderation(
    user_id: UUID,
    payload: AdminUserModerationInput,
    current_admin: Annotated[User, Depends(require_admin)],
    moderation_service: Annotated[
        AdminUserModerationService, Depends(get_admin_user_moderation_service)
    ],
) -> AdminUserModerationOutput:
    action = AdminUserModerationMapper.to_entity(payload)
    now = datetime.now(UTC)
    try:
        updated = moderation_service.apply_action(
            user_id, action, actor_id=current_admin.user_id, now=now
        )
    except ModeratedUserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from error
    except ReportNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        ) from error
    except AccountAlreadyBannedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account is already banned",
        ) from error
    except AccountNotModeratedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not banned or suspended",
        ) from error
    except ReportAlreadyResolvedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report already resolved",
        ) from error
    except ReportNotAboutUserError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report is not about this user",
        ) from error
    except SelfModerationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admins cannot moderate their own account",
        ) from error
    return AdminUserModerationAssembler.to_dto(updated, now=now)
