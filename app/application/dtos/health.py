from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthOutput:
    """Output returned by the health-check use case."""

    status: str
