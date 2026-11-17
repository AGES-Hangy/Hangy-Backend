"""Send push messages only after the transaction that created them commits.

The dispatcher asks for a push while the business operation is still open. If
the push went out right there, a later rollback would leave users notified of
something that never happened, and every Expo round trip (10 s timeout each)
would hold the HTTP request and its row locks. Instead each push is queued on
the SQLAlchemy session and handed to a small thread pool once that session
commits; a rollback drops the queue.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.domain.services.push import PushSender

__all__ = ["AfterCommitPushSender", "push_executor"]

logger = logging.getLogger(__name__)

_PENDING_KEY = "hangy_pending_pushes"
_LISTENING_KEY = "hangy_push_listeners"

# Shared by every request; a few workers are enough for Expo's batch API.
push_executor: Executor = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="hangy-push"
)


@dataclass(frozen=True, slots=True)
class _PendingPush:
    tokens: list[str]
    title: str
    body: str
    data: dict[str, str]


TokenCleanup = Callable[[list[str]], None]


def _delete_rejected_tokens(tokens: list[str]) -> None:
    """Remove DeviceNotRegistered tokens in a session of their own."""
    from app.infrastructure.repository.device import SqlAlchemyUserDeviceRepository
    from app.infrastructure.repository.session import SessionLocal

    with SessionLocal() as db:
        SqlAlchemyUserDeviceRepository(db).delete_by_tokens(tokens)


class AfterCommitPushSender:
    """A PushSender that defers the real send until `session` commits.

    `send` always returns no rejected tokens: they are only known once Expo
    answers, so their cleanup happens in the background with its own session
    (never committing the caller's transaction halfway).
    """

    def __init__(
        self,
        session: Session,
        sender: PushSender,
        executor: Executor | None = None,
        cleanup: TokenCleanup = _delete_rejected_tokens,
    ) -> None:
        self.session = session
        self.sender = sender
        self.executor = executor or push_executor
        self.cleanup = cleanup
        self._listen()

    def send(
        self, tokens: list[str], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        if tokens:
            self.session.info.setdefault(_PENDING_KEY, []).append(
                _PendingPush(list(tokens), title, body, dict(data))
            )
        return []

    def _listen(self) -> None:
        # One set of listeners per session, however many senders it gets.
        if self.session.info.get(_LISTENING_KEY):
            return
        self.session.info[_LISTENING_KEY] = True
        event.listen(self.session, "after_commit", self._flush)
        event.listen(self.session, "after_rollback", self._discard)

    def _flush(self, session: Session) -> None:
        pending: list[_PendingPush] = session.info.pop(_PENDING_KEY, [])
        for push in pending:
            self.executor.submit(self._deliver, push)

    @staticmethod
    def _discard(session: Session) -> None:
        session.info.pop(_PENDING_KEY, None)

    def _deliver(self, push: _PendingPush) -> None:
        try:
            rejected = self.sender.send(push.tokens, push.title, push.body, push.data)
            if rejected:
                self.cleanup(rejected)
        except Exception:
            # Never log the payload: it can carry user and event ids.
            logger.exception("Push delivery failed")
