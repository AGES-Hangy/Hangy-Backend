from dataclasses import dataclass
from uuid import UUID

__all__ = ["StartingSoonCandidate"]


@dataclass(frozen=True, slots=True)
class StartingSoonCandidate:
    """A confirmed participation whose event starts soon and was not yet warned."""

    participant_id: UUID
    user_id: UUID
    event_id: UUID