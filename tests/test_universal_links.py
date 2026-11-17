from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.presentation.routes import universal_links


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def configured_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        universal_links,
        "settings",
        SimpleNamespace(
            android_sha256_fingerprints=("AA:BB:CC", "11:22:33"),
            app_store_url="https://apps.apple.com/app/hangy",
            apple_team_id="TEAM123",
            google_play_url="https://play.google.com/store/apps/details?id=hangy",
            invite_link_base_url="hangy://invite/",
        ),
    )


def test_invite_page_is_generic_for_any_token(
    client: TestClient,
    configured_settings: None,
) -> None:
    existing = client.get("/invite/existing-token")
    nonexistent = client.get("/invite/nonexistent-token")

    assert existing.status_code == status.HTTP_200_OK
    assert nonexistent.status_code == status.HTTP_200_OK
    assert existing.headers["content-type"].startswith("text/html")
    assert nonexistent.headers["content-type"].startswith("text/html")
    assert "Você foi convidado para um evento no Hangy." in existing.text
    assert "Abrir no app" in existing.text
    assert "hangy://invite/existing-token" in existing.text
    assert existing.text.replace("existing-token", "TOKEN") == nonexistent.text.replace(
        "nonexistent-token", "TOKEN"
    )


def test_invite_page_escapes_the_token(
    client: TestClient,
    configured_settings: None,
) -> None:
    response = client.get("/invite/%22%3E%3Cimg%20src=x%20onerror=alert(1)%3E")

    assert response.status_code == status.HTTP_200_OK
    assert "<img" not in response.text
    assert "&lt;img" in response.text


def test_invite_page_explains_when_store_links_are_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        universal_links,
        "settings",
        SimpleNamespace(
            android_sha256_fingerprints=(),
            app_store_url="",
            apple_team_id="",
            google_play_url="",
            invite_link_base_url="hangy://invite/",
        ),
    )

    response = client.get("/invite/any-token")

    assert response.status_code == status.HTTP_200_OK
    assert "ainda não está disponível nas lojas" in response.text
    assert "Baixar na App Store" not in response.text
    assert "Baixar no Google Play" not in response.text


def test_apple_association_returns_expected_json(
    client: TestClient,
    configured_settings: None,
) -> None:
    response = client.get("/.well-known/apple-app-site-association")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "application/json"
    assert response.history == []
    assert response.json() == {
        "applinks": {
            "details": [
                {
                    "appIDs": ["TEAM123.br.pucrs.ages.hangy"],
                    "components": [{"/": "/invite/*"}],
                }
            ]
        }
    }


def test_android_asset_links_returns_expected_json(
    client: TestClient,
    configured_settings: None,
) -> None:
    response = client.get("/.well-known/assetlinks.json")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "application/json"
    assert response.json() == [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "br.pucrs.ages.hangy",
                "sha256_cert_fingerprints": ["AA:BB:CC", "11:22:33"],
            },
        }
    ]


def test_association_files_return_not_found_without_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        universal_links,
        "settings",
        SimpleNamespace(
            android_sha256_fingerprints=(),
            app_store_url="",
            apple_team_id="",
            google_play_url="",
            invite_link_base_url="hangy://invite/",
        ),
    )

    apple_response = client.get("/.well-known/apple-app-site-association")
    android_response = client.get("/.well-known/assetlinks.json")

    assert apple_response.status_code == status.HTTP_404_NOT_FOUND
    assert android_response.status_code == status.HTTP_404_NOT_FOUND


def test_universal_link_routes_are_hidden_from_openapi(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/invite/{token}" not in paths
    assert "/.well-known/apple-app-site-association" not in paths
    assert "/.well-known/assetlinks.json" not in paths
