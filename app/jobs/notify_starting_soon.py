"""Entry point: python -m app.jobs.notify_starting_soon

Opens a session, warns the participants of events about to start and exits.
Meant to run every few minutes (see infra/terraform/bootstrap-ec2.sh).
"""

import logging

from app.config import settings
from app.domain.services.notification_dispatcher import NotificationDispatcher
from app.domain.services.starting_soon import StartingSoonService
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
    with SessionLocal() as db:
        service = StartingSoonService(
            repository=SqlAlchemyStartingSoonRepository(db),
            dispatcher=NotificationDispatcher(
                repository=SqlAlchemyNotificationRepository(db),
                device_repository=SqlAlchemyUserDeviceRepository(db),
                push_sender=expo_push_sender,
            ),
            window_minutes=settings.starting_soon_window_minutes,
        )
        handled = service.notify_participants()
    logger.info("Starting-soon job finished: %d participant(s) notified", handled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
