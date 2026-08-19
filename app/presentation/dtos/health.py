from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthOutput:
    """Response returned to clients by the health-check endpoint."""

    status: str
