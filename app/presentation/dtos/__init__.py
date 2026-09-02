"""Data transfer objects exchanged with API clients."""

from app.presentation.dtos.auth import RegisterInput, TokenOutput, UserOutput
from app.presentation.dtos.event import (
    CreateEventInput,
    CreateEventOutput,
    EventCreatorOutput,
    EventLocationInput,
)
from app.presentation.dtos.health import HealthOutput
from app.presentation.dtos.tag import TagOutput

__all__ = [
    "CreateEventInput",
    "CreateEventOutput",
    "EventCreatorOutput",
    "EventLocationInput",
    "HealthOutput",
    "RegisterInput",
    "TagOutput",
    "TokenOutput",
    "UserOutput",
]
