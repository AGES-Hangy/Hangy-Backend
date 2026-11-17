__all__ = [
    "BanUserAction",
    "RevertUserModerationAction",
    "SuspendUserAction",
    "UserModerationAction",
]

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BanUserAction:
    report_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SuspendUserAction:
    duration_days: int
    report_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RevertUserModerationAction:
    pass


UserModerationAction = BanUserAction | SuspendUserAction | RevertUserModerationAction
