from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import ReportAssembler
from app.domain.entities import User
from app.domain.enums import ReportTargetEnum
from app.domain.services import (
    CannotReportYourselfError,
    EventDetailsService,
    ExactlyOneReportTargetError,
    ReportAlreadyUnderReviewError,
    ReportParticipantsOnlyError,
    ReportReasonRequiresParticipationError,
    ReportReasonsService,
    ReportService,
    ReportTargetNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.event_details import SqlAlchemyEventDetailsRepository
from app.infrastructure.repository.report import SqlAlchemyReportRepository
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.dependencies.auth import get_current_user
from app.presentation.dtos import (
    ReportCreatedOutput,
    ReportCreateInput,
    ReportReasonOutput,
)
from app.presentation.mappers.report import ReportMapper

router = APIRouter(tags=["Reports"])


def get_report_reasons_service(
    db: Annotated[Session, Depends(get_db)],
) -> ReportReasonsService:
    return ReportReasonsService(
        repository=SqlAlchemyReportRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
        event_visibility=EventDetailsService(
            repository=SqlAlchemyEventDetailsRepository(db)
        ),
    )


def get_report_service(db: Annotated[Session, Depends(get_db)]) -> ReportService:
    return ReportService(
        repository=SqlAlchemyReportRepository(db),
        user_repository=SqlAlchemyUserRepository(db),
        event_visibility=EventDetailsService(
            repository=SqlAlchemyEventDetailsRepository(db)
        ),
    )


CANNOT_REPORT_YOURSELF = "Cannot report yourself"
PARTICIPANTS_ONLY = "Only participants can report this event"
REASON_REQUIRES_PARTICIPATION = "Reason requires participation"
ALREADY_UNDER_REVIEW = "Report already under review"

_UNAUTHORIZED_RESPONSE = {
    "description": "Token ausente, invalido ou expirado.",
    "content": {
        "application/json": {"example": {"detail": "Could not validate credentials"}}
    },
}
_NOT_FOUND_RESPONSE = {
    "description": "O usuario ou o evento nao existe ou nao esta visivel para o autor.",
    "content": {"application/json": {"example": {"detail": "Target not found"}}},
}

CREATE_REPORT_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {
        "description": (
            "Os dois alvos preenchidos ou nenhum alvo; ou o autor denuncia o "
            "proprio perfil ou o proprio evento."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "exactly_one_target": {
                        "summary": "Alvo invalido",
                        "value": {"detail": "Exactly one target is required"},
                    },
                    "yourself": {
                        "summary": "Denuncia de si mesmo",
                        "value": {"detail": CANNOT_REPORT_YOURSELF},
                    },
                }
            }
        },
    },
    status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
    status.HTTP_403_FORBIDDEN: {
        "description": (
            "Evento PRIVATE ou INVITE_ONLY sem participacao aprovada do autor; "
            "ou motivo EXPERIENCE em evento PUBLIC sem participacao aprovada."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "participants_only": {
                        "summary": "Evento privado ou por convite",
                        "value": {"detail": PARTICIPANTS_ONLY},
                    },
                    "reason_requires_participation": {
                        "summary": "Motivo EXPERIENCE em evento publico",
                        "value": {"detail": REASON_REQUIRES_PARTICIPATION},
                    },
                }
            }
        },
    },
    status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
    status.HTTP_409_CONFLICT: {
        "description": (
            "O autor ja tem uma denuncia aberta (PENDING ou REVIEWED) para o "
            "mesmo alvo e o mesmo motivo."
        ),
        "content": {"application/json": {"example": {"detail": ALREADY_UNDER_REVIEW}}},
    },
}

# POST /reports error map
_REPORT_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (
        ExactlyOneReportTargetError,
        status.HTTP_400_BAD_REQUEST,
        "Exactly one target is required",
    ),
    (CannotReportYourselfError, status.HTTP_400_BAD_REQUEST, CANNOT_REPORT_YOURSELF),
    (
        ReportParticipantsOnlyError,
        status.HTTP_403_FORBIDDEN,
        PARTICIPANTS_ONLY,
    ),
    (
        ReportReasonRequiresParticipationError,
        status.HTTP_403_FORBIDDEN,
        REASON_REQUIRES_PARTICIPATION,
    ),
    (ReportTargetNotFoundError, status.HTTP_404_NOT_FOUND, "Target not found"),
    (
        ReportAlreadyUnderReviewError,
        status.HTTP_409_CONFLICT,
        ALREADY_UNDER_REVIEW,
    ),
)

# GET /reports/reasons error map — CannotReportYourselfError is 403 here
# (the caller cannot report this target at all), unlike POST where it is 400.
_REASONS_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (CannotReportYourselfError, status.HTTP_403_FORBIDDEN, CANNOT_REPORT_YOURSELF),
    (ReportParticipantsOnlyError, status.HTTP_403_FORBIDDEN, PARTICIPANTS_ONLY),
    (ReportTargetNotFoundError, status.HTTP_404_NOT_FOUND, "Target not found"),
)


def _translate_error(
    error: Exception,
    table: tuple[tuple[type[Exception], int, str], ...],
) -> HTTPException:
    for error_type, status_code, detail in table:
        if isinstance(error, error_type):
            return HTTPException(status_code=status_code, detail=detail)
    raise error


@router.get(
    "/reports/reasons",
    response_model=list[ReportReasonOutput],
    status_code=status.HTTP_200_OK,
    summary="Listar os motivos de denúncia de um alvo",
    description=(
        "Devolve os motivos de denúncia para o alvo informado (`target` = "
        "`USER` ou `EVENT`, mais `target_id`), na ordem em que devem aparecer "
        "na lista de radios. Estabelecimento é um `USER`. Cada motivo traz o "
        "`scope` (`CONTENT` ou `EXPERIENCE`; em perfil é sempre `CONTENT`) e se "
        "está `available` para quem pergunta; quando não está, "
        "`unavailable_reason` é `PARTICIPANTS_ONLY` (motivo `EXPERIENCE` de "
        "quem não participa de um evento público) ou `ALREADY_REPORTED` (já "
        "existe denúncia aberta do autor por esse motivo). Alvo que o autor não "
        "pode denunciar de jeito nenhum devolve `403`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "Evento PRIVATE ou INVITE_ONLY sem participacao aprovada, "
                "proprio perfil ou proprio evento."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "participants_only": {
                            "summary": "Evento privado ou por convite",
                            "value": {"detail": PARTICIPANTS_ONLY},
                        },
                        "yourself": {
                            "summary": "Proprio perfil ou evento",
                            "value": {"detail": CANNOT_REPORT_YOURSELF},
                        },
                    }
                }
            },
        },
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": (
                "`target` ou `target_id` ausente, ou `target` diferente de "
                "`USER` e `EVENT`."
            ),
        },
    },
)
def list_report_reasons(
    target: Annotated[
        ReportTargetEnum,
        Query(description="Tipo de alvo da denuncia: USER ou EVENT."),
    ],
    target_id: Annotated[
        UUID,
        Query(description="Id do usuario ou do evento que seria denunciado."),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReportReasonsService, Depends(get_report_reasons_service)],
) -> list[ReportReasonOutput]:
    assert current_user.user_id is not None
    try:
        reasons = service.get_reasons(current_user.user_id, target, target_id)
    except (
        CannotReportYourselfError,
        ReportParticipantsOnlyError,
        ReportTargetNotFoundError,
    ) as error:
        raise _translate_error(error, _REASONS_ERRORS) from error
    return ReportAssembler.to_reason_dtos(reasons)


@router.post(
    "/reports",
    response_model=ReportCreatedOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Denunciar um perfil ou um evento",
    description=(
        "Registra a denuncia de um usuario (inclui estabelecimentos) ou de um "
        "evento: exatamente um entre reported_user_id e reported_event_id. O "
        "autor tem no maximo uma denuncia aberta (PENDING ou REVIEWED) por "
        "alvo e motivo. Em evento, motivos EXPERIENCE (MISLEADING_EVENT, "
        "HARASSMENT, SAFETY_CONCERN) exigem participacao aprovada, e evento "
        "PRIVATE ou INVITE_ONLY so aceita denuncia de participantes. O autor "
        "nunca aparece na resposta. Denunciar nao bloqueia nem oculta o alvo e "
        "nao dispara notificacao."
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
        CannotReportYourselfError,
        ReportParticipantsOnlyError,
        ReportReasonRequiresParticipationError,
        ReportTargetNotFoundError,
        ReportAlreadyUnderReviewError,
    ) as error:
        raise _translate_error(error, _REPORT_ERRORS) from error
    return ReportAssembler.to_created_dto(report)
