from app.config import settings
from app.domain.services.password_reset import EmailSender
from app.infrastructure.email.console_email_sender import ConsoleEmailSender
from app.infrastructure.email.ses_email_sender import SesEmailSender

__all__ = ["ConsoleEmailSender", "SesEmailSender", "get_email_sender"]


def get_email_sender() -> EmailSender:
    """FastAPI dependency; construction never resolves credentials or contacts SES."""
    if settings.email_backend == "ses":
        return SesEmailSender()
    return ConsoleEmailSender()
