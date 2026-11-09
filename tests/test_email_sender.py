from dataclasses import replace
from email import message_from_string
from pathlib import Path
from runpy import run_path
from unittest.mock import Mock

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

from app.config import Settings, settings
from app.infrastructure.email import (
    ConsoleEmailSender,
    SesEmailSender,
    get_email_sender,
)


@pytest.fixture
def email_settings(monkeypatch):
    configured = replace(
        settings,
        email_backend="console",
        email_from="Hangy <reset@hangy.example>",
        ses_region="us-east-2",
    )
    for module in (
        "app.infrastructure.email",
        "app.infrastructure.email.ses_email_sender",
        "app.infrastructure.email.console_email_sender",
    ):
        monkeypatch.setattr(f"{module}.settings", configured)
    return configured


def test_console_prints_email_to_stdout_without_logging(email_settings, capsys, caplog):
    sender = get_email_sender()
    assert isinstance(sender, ConsoleEmailSender)

    sender.send("user@hangy.example", "Assunto", "Código: 123456")

    message = message_from_string(capsys.readouterr().out)
    assert message["From"] == email_settings.email_from
    assert message["To"] == "user@hangy.example"
    assert message["Subject"] == "Assunto"
    assert message.get_payload(decode=True).decode("utf-8").strip() == "Código: 123456"
    assert "123456" not in caplog.text


def test_factory_ses_and_construction_are_lazy(email_settings, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.email.settings",
        replace(email_settings, email_backend="ses"),
    )
    create_client = Mock(side_effect=AssertionError("Must be lazy"))
    monkeypatch.setattr(
        "app.infrastructure.email.ses_email_sender.boto3.client", create_client
    )
    assert isinstance(get_email_sender(), SesEmailSender)
    create_client.assert_not_called()


@mock_aws
def test_ses_sends_expected_utf8_content(email_settings, monkeypatch):
    client = boto3.client("sesv2", region_name=email_settings.ses_region)
    client.create_email_identity(EmailIdentity="reset@hangy.example")
    create_client = Mock(return_value=client)
    monkeypatch.setattr(
        "app.infrastructure.email.ses_email_sender.boto3.client", create_client
    )
    sender = SesEmailSender()
    # Stubber checks the exact SESv2 wire parameters; moto handles the send too.
    expected = {
        "FromEmailAddress": email_settings.email_from,
        "Destination": {"ToAddresses": ["user@hangy.example"]},
        "Content": {
            "Simple": {
                "Subject": {"Data": "Redefinição", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "Código: 123456", "Charset": "UTF-8"}},
            }
        },
    }
    with Stubber(client) as stubber:
        stubber.add_response("send_email", {"MessageId": "test-message"}, expected)
        sender.send("user@hangy.example", "Redefinição", "Código: 123456")
        stubber.assert_no_pending_responses()
    sender.send("user@hangy.example", "Redefinição", "Código: 123456")
    assert create_client.call_count == 1
    assert create_client.call_args.args == ("sesv2",)
    assert create_client.call_args.kwargs["region_name"] == "us-east-2"


@pytest.mark.parametrize("backend", ["", "smtp", "  "])
def test_invalid_backend_is_rejected(backend):
    with pytest.raises(RuntimeError, match="EMAIL_BACKEND"):
        Settings(email_backend=backend)


@pytest.mark.parametrize("overrides", [{"email_from": ""}, {"ses_region": ""}])
def test_ses_requires_sender_and_region(overrides):
    values = {"email_backend": "ses", "email_from": "reset@hangy.example"}
    values.update(overrides)
    with pytest.raises(RuntimeError, match="EMAIL_FROM"):
        Settings(**values)


@pytest.mark.parametrize("region", [None, "", "   ", " eu-west-1 "])
def test_environment_normalizes_email_configuration(monkeypatch, region):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    monkeypatch.setenv("EMAIL_BACKEND", " SES ")
    monkeypatch.setenv("EMAIL_FROM", "  Hangy <reset@hangy.example>  ")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    if region is None:
        monkeypatch.delenv("SES_REGION", raising=False)
    else:
        monkeypatch.setenv("SES_REGION", region)
    configured = run_path(str(Path("app/config.py")))["settings"]
    assert configured.email_backend == "ses"
    assert configured.email_from == "Hangy <reset@hangy.example>"
    assert configured.ses_region == (
        "eu-west-1" if region and region.strip() else "us-east-2"
    )
