"""Data transfer objects exchanged with API clients."""

from app.presentation.dtos.auth import RegisterInput, TokenOutput, UserOutput
from app.presentation.dtos.event import CancelEventInput, CancelEventOutput
from app.presentation.dtos.health import HealthOutput
from app.presentation.dtos.tag import TagOutput

__all__ = [
    "CancelEventInput",
    "CancelEventOutput",
    "HealthOutput",
    "RegisterInput",
    "TagOutput",
    "TokenOutput",
    "UserOutput",
]
