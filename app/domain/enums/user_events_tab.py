from enum import StrEnum


class UserEventsTabEnum(StrEnum):
    CONFIRMED = "confirmed"
    # Kept for GET /users/me/events, where it is an alias of HISTORY.
    PAST = "past"
    HISTORY = "history"
    CREATED = "created"
    INTERESTS = "interests"
