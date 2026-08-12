from app.application.dtos import HealthOutput
from app.domain.entities import HealthStatus


class GetHealth:
    """Return the current application health state."""

    def execute(self) -> HealthOutput:
        health_status = HealthStatus(status="ok")
        return HealthOutput(status=health_status.status)
