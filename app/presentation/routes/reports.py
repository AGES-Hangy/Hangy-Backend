from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import ReportAssembler
from app.domain.entities import User
from app.domain.services import (
    EventDetailsService,
    ExactlyOneReportTargetError,
    InvalidReportReasonError,
    ReportAlreadyUnderReviewError,
    ReportService,
    ReportTargetNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event_details import SqlAlchemyEventDetailsRepository
from app.infrastructure.repository.report import SqlAlchemyReportRepository
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.dependencies.auth import get_current_user
from app.presentation.dtos import ReportCreatedOutput, ReportCreateInput
from app.presentation.mappers.report import ReportMapper

router = APIRouter(prefix="/reports", tags=["Reports"])


def get_report_service(db: Annotated[Session, Depends(get_db)]) -> ReportService:
    return ReportService(
        repository=SqlAlchemyReportRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
        event_visibility=EventDetailsService(
            repository=SqlAlchemyEventDetailsRepository(db)
        ),
    )


CREATE_REPORT_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {
        "description": (
            "Os dois alvos preenchidos, nenhum alvo, ou motivo fora da lista."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "target": {"value": {"detail": "Exactly one target is required"}},
                    "reason": {"value": {"detail": "Invalid report reason"}},
                }
            }
        },
    },
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Token ausente, invalido ou expirado.",
        "content": {
            "application/json": {
                "example": {"detail": "Could not validate credentials"}
            }
        },
    },
    status.HTTP_404_NOT_FOUND: {
        "description": (
            "O usuario ou o evento nao existe ou nao esta visivel para o autor."
        ),
        "content": {"application/json": {"example": {"detail": "Target not found"}}},
    },
    status.HTTP_409_CONFLICT: {
        "description": ("O autor ja tem uma denuncia PENDING para o mesmo alvo."),
        "content": {
            "application/json": {"example": {"detail": "Report already under review"}}
        },
    },
}

_REPORT_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (
        ExactlyOneReportTargetError,
        status.HTTP_400_BAD_REQUEST,
        "Exactly one target is required",
    ),
    (
        InvalidReportReasonError,
        status.HTTP_400_BAD_REQUEST,
        "Invalid report reason",
    ),
    (ReportTargetNotFoundError, status.HTTP_404_NOT_FOUND, "Target not found"),
    (
        ReportAlreadyUnderReviewError,
        status.HTTP_409_CONFLICT,
        "Report already under review",
    ),
)


def _translate_report_error(error: Exception) -> HTTPException | None:
    for error_type, status_code, detail in _REPORT_ERRORS:
        if isinstance(error, error_type):
            return HTTPException(status_code=status_code, detail=detail)
    return None


@router.post(
    "",
    response_model=ReportCreatedOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Denunciar um perfil ou um evento",
    description=(
        "Registra a denuncia de um usuario (inclui estabelecimentos) ou de um "
        "evento: exatamente um entre reported_user_id e reported_event_id. O "
        "autor nunca aparece na resposta. Denunciar nao bloqueia nem oculta o "
        "alvo e nao dispara notificacao."
    ),
    responses=CREATE_REPORT_RESPONSES,
)
def create_report(
    payload: ReportCreateInput,
    current_user: Annotated[User, Depends(get_current_user)],
    report_service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportCreatedOutput:
    assert current_user.user_id is not None
    try:
        new_report = ReportMapper.to_new_report(payload, current_user.user_id)
        report = report_service.create_report(new_report)
    except (
        ExactlyOneReportTargetError,
        InvalidReportReasonError,
        ReportTargetNotFoundError,
        ReportAlreadyUnderReviewError,
    ) as error:
        http_error = _translate_report_error(error)
        assert http_error is not None
        raise http_error from error
    return ReportAssembler.to_created_dto(report)
