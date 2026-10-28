from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app.domain.assemblers import AuditLogAssembler
from app.domain.entities import User
from app.domain.enums import AuditTargetTypeEnum
from app.domain.services import AuditLogger, AuditLogService, InvalidPaginationError
from app.infrastructure.repository import get_db
from app.infrastructure.repository.audit_log import SqlAlchemyAuditLogRepository
from app.presentation.dtos import AuditLogPaginatedResponse
from app.presentation.routes.auth import get_current_admin

router = APIRouter(prefix="/admin/audit-log", tags=["Admin"])


def _parse_limit(value: str | int) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error


def get_audit_log_service(db: Annotated[Session, Depends(get_db)]) -> AuditLogService:
    return AuditLogService(repository=SqlAlchemyAuditLogRepository(db))


def get_audit_logger(db: Annotated[Session, Depends(get_db)]) -> AuditLogger:
    """Shared factory for other admin routes (ban, suspend, report, tag CRUD)."""
    repository = SqlAlchemyAuditLogRepository(db)
    return AuditLogger(repository=repository, label_resolver=repository)


@router.get(
    "",
    response_model=AuditLogPaginatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar o log de auditoria de ações administrativas",
    description=(
        "Lista os registros de auditoria mais recentes primeiro. Filtra "
        "opcionalmente por `target_type` (USER, REPORT ou TAG)."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Parâmetros de paginação inválidos.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid pagination parameters"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "O usuário autenticado não é administrador.",
            "content": {
                "application/json": {"example": {"detail": "Admin access required"}}
            },
        },
    },
)
def get_audit_log(
    current_admin: Annotated[User, Depends(get_current_admin)],
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
    target_type: Annotated[
        AuditTargetTypeEnum | None,
        Query(description="Filtra por USER, REPORT ou TAG"),
    ] = None,
    limit: Annotated[
        int,
        BeforeValidator(_parse_limit),
        Query(description="Tamanho da página (1–100)."),
    ] = 20,
    cursor: Annotated[str | None, Query(description="Cursor opaco de paginação.")] = (
        None
    ),
) -> AuditLogPaginatedResponse:
    assert current_admin.user_id is not None
    try:
        entries, next_cursor = audit_log_service.list_audit_log(
            target_type=target_type, limit=limit, cursor=cursor
        )
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error

    return AuditLogAssembler.to_paginated_response(
        entries, next_cursor, current_admin.user_id
    )
