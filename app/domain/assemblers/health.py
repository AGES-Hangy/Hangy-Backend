from app.domain.entities import HealthStatus
from app.presentation.dtos import HealthOutput


class HealthAssembler:
    """Build health-check response DTOs from domain entities."""

    @staticmethod
    def to_dto(health_status: HealthStatus) -> HealthOutput:
        return HealthOutput(status=health_status.status)
