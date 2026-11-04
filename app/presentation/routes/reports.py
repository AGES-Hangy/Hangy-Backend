from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.domain.assemblers import ReportAssembler
from app.domain.entities import User
from app.domain.enums import ReportTargetEnum
from app.domain.services import ReportReasonsService
from app.presentation.dependencies.auth import get_current_user
from app.presentation.dtos import ReportReasonOutput

router = APIRouter(tags=["Reports"])


def get_report_reasons_service() -> ReportReasonsService:
    return ReportReasonsService()


@router.get(
    "/reports/reasons",
    response_model=list[ReportReasonOutput],
    status_code=status.HTTP_200_OK,
    summary="Listar os motivos de denúncia de um alvo",
    description=(
        "Devolve os motivos de denúncia disponíveis para o tipo de alvo "
        "informado em `target` (`USER` ou `EVENT`), na ordem em que devem "
        "aparecer na lista de radios. Estabelecimento é um `USER`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou invalido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "`target` ausente ou diferente de `USER` e `EVENT`.",
        },
    },
)
def list_report_reasons(
    target: Annotated[
        ReportTargetEnum,
        Query(description="Tipo de alvo da denuncia: USER ou EVENT."),
    ],
    _current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ReportReasonsService, Depends(get_report_reasons_service)],
) -> list[ReportReasonOutput]:
    return ReportAssembler.to_reason_dtos(service.get_reasons(target))
