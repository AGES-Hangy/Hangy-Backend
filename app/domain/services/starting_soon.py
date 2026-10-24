import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.domain.entities import StartingSoonCandidate
from app.domain.enums import NotificationTypeEnum
from app.domain.services.notification_dispatcher import NotificationDispatcher

__all__ = ["StartingSoonRepository", "StartingSoonService"]

logger = logging.getLogger(__name__)


class StartingSoonRepository(Protocol):
    def list_unnotified_candidates(
        self, starts_after: datetime, starts_until: datetime
    ) -> list[StartingSoonCandidate]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class StartingSoonService:
    """Warns confirmed participants shortly before their event starts.

    The window is "starts within N minutes and has not started yet", not
    "starts in exactly N minutes", so a late or missed run is recovered by the
    next one. Each participation is warned once: the repository only returns
    participations with no EVENT_STARTING_SOON notification yet, and each
    notification is committed right after it is dispatched.
    """

    def __init__(
        self,
        repository: StartingSoonRepository,
        dispatcher: NotificationDispatcher,
        window_minutes: int,
    ) -> None:
        self.repository = repository
        self.dispatcher = dispatcher
        self.window = timedelta(minutes=window_minutes)

    def notify_participants(self, now: datetime | None = None) -> int:
        """Dispatch the warnings and return how many participants were handled."""
        now = now or datetime.now(UTC)
        candidates = self.repository.list_unnotified_candidates(now, now + self.window)

        handled = 0
        for candidate in candidates:
            try:
                # The dispatcher swallows send errors, so a failure for one
                # participant never stops the others. It does not commit: the
                # commit here makes the "already warned" row visible to the
                # next run.
                self.dispatcher.dispatch(
                    NotificationTypeEnum.EVENT_STARTING_SOON,
                    recipient_id=candidate.user_id,
                    participant_id=candidate.participant_id,
                )
                self.repository.commit()
                handled += 1
            except Exception:
                logger.exception(
                    "Starting-soon notification failed for participant %s",
                    candidate.participant_id,
                )
                self.repository.rollback()
        return handled
