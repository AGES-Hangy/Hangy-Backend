from fastapi import APIRouter, status

from app.application.dtos import HealthOutput
from app.application.use_cases import GetHealth

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthOutput,
    status_code=status.HTTP_200_OK,
    summary="Verificar a saúde da aplicação",
    description="Retorna o estado atual da API.",
)
def health_check() -> HealthOutput:
    return GetHealth().execute()
