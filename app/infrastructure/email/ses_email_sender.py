"""Synchronous SES adapter using the SDK credential chain and a lazy client."""

import boto3
from botocore.config import Config

from app.config import settings

__all__ = ["SesEmailSender"]


class SesEmailSender:
    def __init__(self) -> None:
        self._client = None

    def send(self, recipient: str, subject: str, body: str) -> None:
        if self._client is None:
            self._client = boto3.client(
                "sesv2",
                region_name=settings.ses_region,
                config=Config(
                    connect_timeout=5,
                    read_timeout=10,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            )
        self._client.send_email(
            FromEmailAddress=settings.email_from,
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
