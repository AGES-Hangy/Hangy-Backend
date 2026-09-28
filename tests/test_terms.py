from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_current_terms_returns_200() -> None:
    response = client.get("/terms/current")

    assert response.status_code == 200
    body = response.json()
    assert "version" in body
    assert "published_at" in body
    assert "url" in body
    assert "summary" in body


def test_get_current_terms_response_fields() -> None:
    response = client.get("/terms/current")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["version"], str)
    assert isinstance(body["published_at"], str)
    assert isinstance(body["url"], str)
    assert isinstance(body["summary"], str)


def test_get_current_terms_no_version_returns_404(monkeypatch) -> None:
    from dataclasses import replace

    import app.config as config_module

    empty_settings = replace(config_module.settings, terms_version="")
    monkeypatch.setattr(config_module, "settings", empty_settings)

    import app.presentation.routes.terms as terms_module

    monkeypatch.setattr(terms_module, "settings", empty_settings)

    response = client.get("/terms/current")

    assert response.status_code == 404
    assert response.json()["detail"] == "No terms version published"


def test_terms_endpoint_is_in_openapi_schema() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/terms/current" in response.json()["paths"]
