import os
import runpy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.services.auth import LOGIN_FAILURE_LIMIT
from tests.review_helpers import (
    PASSWORD,
    add_user,
    headers_for,
    personal_payload,
)


def test_email_is_case_insensitive_for_register_login_and_duplicates(
    review_client,
) -> None:
    client, _ = review_client
    created = client.post("/auth/register", json=personal_payload(" Ana@Exemplo.COM "))
    assert created.status_code == 201
    assert created.json()["user"]["email"] == "ana@exemplo.com"

    login = client.post(
        "/auth/login", json={"email": "ANA@exemplo.com", "password": PASSWORD}
    )
    duplicate = client.post(
        "/auth/register", json=personal_payload("ana@EXEMPLO.com", seed=987654321)
    )

    assert login.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email is already registered"}


def test_legacy_mixed_case_email_still_logs_in(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        add_user(db, email="Legado@Exemplo.com", password=PASSWORD)

    response = client.post(
        "/auth/login", json={"email": "legado@exemplo.com", "password": PASSWORD}
    )

    assert response.status_code == 200


def test_oversized_password_is_rejected_before_hashing(review_client) -> None:
    client, _ = review_client
    response = client.post(
        "/auth/login", json={"email": "x@exemplo.com", "password": "a" * 129}
    )
    assert response.status_code == 422


def test_login_is_rate_limited_per_email_after_repeated_failures(
    review_client,
) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        add_user(db, email="alvo@exemplo.com", password=PASSWORD)
    wrong = {"email": "alvo@exemplo.com", "password": "errada-123"}

    statuses = [
        client.post("/auth/login", json=wrong).status_code
        for _ in range(LOGIN_FAILURE_LIMIT)
    ]
    blocked = client.post(
        "/auth/login", json={"email": "alvo@exemplo.com", "password": PASSWORD}
    )
    other_email = client.post(
        "/auth/login", json={"email": "outra@exemplo.com", "password": PASSWORD}
    )

    assert statuses == [401] * LOGIN_FAILURE_LIMIT
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many login attempts"}
    assert int(blocked.headers["Retry-After"]) > 0
    assert other_email.status_code == 401


def test_password_reset_rate_limit_sends_retry_after(review_client) -> None:
    client, _ = review_client
    responses = [
        client.post(
            "/auth/password-reset/request", json={"email": "ninguem@exemplo.com"}
        )
        for _ in range(4)
    ]
    assert [response.status_code for response in responses] == [202, 202, 202, 429]
    assert int(responses[-1].headers["Retry-After"]) > 0


def test_register_rejects_a_terms_version_other_than_the_current(
    review_client,
) -> None:
    client, _ = review_client
    payload = personal_payload("termos@exemplo.com")
    payload["accepted_terms_version"] = "1999-01-01"

    response = client.post("/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Terms version is outdated"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test, http://b.test", ("http://a.test", "http://b.test")),
        ("http://a.test,,http://b.test,", ("http://a.test", "http://b.test")),
        ("  http://a.test  ", ("http://a.test",)),
    ],
)
def test_cors_origins_are_trimmed_and_empty_entries_dropped(
    monkeypatch, raw, expected
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", raw)
    config = runpy.run_path(os.path.join("app", "config.py"))
    assert config["settings"].cors_origins == expected


def test_cors_preflight_allows_a_trimmed_origin(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    origins = runpy.run_path(os.path.join("app", "config.py"))["settings"].cors_origins
    probe = FastAPI()
    probe.add_middleware(
        CORSMiddleware, allow_origins=list(origins), allow_methods=["*"]
    )
    client = TestClient(probe)

    allowed = client.options(
        "/",
        headers={"Origin": "http://b.test", "Access-Control-Request-Method": "GET"},
    )
    denied = client.options(
        "/",
        headers={"Origin": "http://c.test", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://b.test"
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/events"),
        ("get", "/events/nearby?latitude=-30&longitude=-51"),
        ("get", "/events/{event_id}"),
        ("get", "/events/{event_id}/share"),
        ("post", "/events/{event_id}/invite-link"),
        ("post", "/events/{event_id}/participation"),
        ("delete", "/events/{event_id}/participation"),
        ("get", "/events/{event_id}/participants"),
        ("patch", "/events/{event_id}/participants/{event_id}"),
        ("patch", "/events/{event_id}"),
        ("patch", "/events/{event_id}/cancel"),
        ("post", "/invites/some-token/accept"),
    ],
)
@pytest.mark.parametrize("account", ["banned", "deleted"])
def test_banned_or_deleted_accounts_never_get_a_server_error(
    review_client, method, path, account
) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        user_id = add_user(
            db, banned_at=datetime.now(UTC) if account == "banned" else None
        )
        if account == "deleted":
            from app.infrastructure.repository.models import UserModel

            db.get(UserModel, user_id).deleted_at = datetime.now(UTC)
            db.commit()

    response = getattr(client, method)(
        path.format(event_id=uuid4()), headers=headers_for(user_id)
    )

    expected = 401 if account == "banned" else 403
    assert response.status_code == expected
