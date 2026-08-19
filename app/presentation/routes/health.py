from fastapi import APIRouter, status

from app.domain.assemblers import HealthAssembler
from app.domain.services import GetHealth
from app.presentation.dtos import HealthOutput

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthOutput,
    status_code=status.HTTP_200_OK,
    summary="Verificar a saúde da aplicação",
    description="Retorna o estado atual da API.",
)
def health_check() -> HealthOutput:
    health_status = GetHealth().execute()
    return HealthAssembler.to_dto(health_status)
