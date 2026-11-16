"""Entry point: python -m app.jobs.notify_starting_soon

Opens a session, warns the participants of events about to start and exits.
Meant to run every few minutes (see infra/terraform/bootstrap-ec2.sh).
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.domain.services.notification_dispatcher import NotificationDispatcher
from app.domain.services.starting_soon import StartingSoonService
from app.infrastructure.push.after_commit import AfterCommitPushSender
from app.infrastructure.push.expo_push_sender import expo_push_sender
from app.infrastructure.repository.device import SqlAlchemyUserDeviceRepository
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.infrastructure.repository.session import SessionLocal
from app.infrastructure.repository.starting_soon import SqlAlchemyStartingSoonRepository

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # The job owns its pool so it can wait for every push before exiting.
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hangy-push")
    with SessionLocal() as db:
        service = StartingSoonService(
            repository=SqlAlchemyStartingSoonRepository(db),
            dispatcher=NotificationDispatcher(
                repository=SqlAlchemyNotificationRepository(db),
                device_repository=SqlAlchemyUserDeviceRepository(db),
                push_sender=AfterCommitPushSender(
                    db, expo_push_sender, executor=executor
                ),
            ),
            window_minutes=settings.starting_soon_window_minutes,
        )
        handled = service.notify_participants()
    # Pushes leave after each commit on worker threads; let them finish before
    # the process exits.
    executor.shutdown(wait=True)
    logger.info("Starting-soon job finished: %d participant(s) notified", handled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
