from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Represents the availability state of the application."""

    status: str
