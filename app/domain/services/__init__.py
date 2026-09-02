"""Services that implement domain business logic."""

from app.domain.services.auth import (
    AuthService,
    DuplicateEmailError,
    InvalidAccessTokenError,
)
from app.domain.services.event import (
    EventEndsBeforeItStartsError,
    EventsService,
    EventStartsInThePastError,
    EventTagNotFoundError,
    InvalidEventCoordinatesError,
    TooManyEventTagsError,
)
from app.domain.services.get_health import GetHealth
from app.domain.services.tags import (
    InvalidTagFilterError,
    TagNotFoundError,
    TagsService,
)

__all__ = [
    "AuthService",
    "DuplicateEmailError",
    "EventEndsBeforeItStartsError",
    "EventStartsInThePastError",
    "EventTagNotFoundError",
    "EventsService",
    "GetHealth",
    "InvalidAccessTokenError",
    "InvalidEventCoordinatesError",
    "InvalidTagFilterError",
    "TagNotFoundError",
    "TagsService",
    "TooManyEventTagsError",
]
