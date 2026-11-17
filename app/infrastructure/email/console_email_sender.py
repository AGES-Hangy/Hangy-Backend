"""Development email delivery, explicitly printed to stdout rather than logged."""

from email.message import EmailMessage

from app.config import settings

__all__ = ["ConsoleEmailSender"]


class ConsoleEmailSender:
    def send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        print(str(message))
