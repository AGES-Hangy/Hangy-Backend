from app.domain.entities import HealthStatus


class GetHealth:
    """Return the current application health state."""

    def execute(self) -> HealthStatus:
        return HealthStatus(status="ok")
