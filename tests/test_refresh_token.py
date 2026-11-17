from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.infrastructure.repository.models import RefreshTokenModel, UserModel
from tests.review_helpers import (
    PASSWORD,
    personal_payload,
)


def _login(client, email="ana@exemplo.com", seed=123456789):
    client.post("/auth/register", json=personal_payload(email, seed))
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()


def test_login_and_register_return_a_refresh_token(review_client) -> None:
    client, _ = review_client
    register = client.post("/auth/register", json=personal_payload("bia@exemplo.com"))
    assert register.status_code == 201
    body = register.json()
    assert body["refresh_token"]
    assert body["expires_in"] == 30 * 60
    assert body["refresh_expires_in"] == 30 * 24 * 60 * 60


def test_refresh_rotates_and_the_new_access_token_works(review_client) -> None:
    client, _ = review_client
    session = _login(client)

    refreshed = client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )

    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["refresh_token"] != session["refresh_token"]
    me = client.get(
        "/users/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200


def test_reusing_a_spent_refresh_token_revokes_the_whole_family(review_client) -> None:
    client, _ = review_client
    session = _login(client)
    first = client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    ).json()

    reused = client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )
    after_reuse = client.post(
        "/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )

    assert reused.status_code == 401
    assert reused.json() == {"detail": "Invalid refresh token"}
    assert after_reuse.status_code == 401


def test_logout_revokes_the_refresh_token(review_client) -> None:
    client, _ = review_client
    session = _login(client)

    logout = client.post(
        "/auth/logout", json={"refresh_token": session["refresh_token"]}
    )
    refresh = client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )

    assert logout.status_code == 204
    assert refresh.status_code == 401
    assert (
        client.post("/auth/logout", json={"refresh_token": "unknown"}).status_code
        == 204
    )


def test_expired_unknown_and_pre_password_change_tokens_are_rejected(
    review_client,
) -> None:
    client, session_factory = review_client
    expired = _login(client, "a@exemplo.com")
    stale = _login(client, "b@exemplo.com", seed=987654321)
    with session_factory() as db:
        for row in db.scalars(select(RefreshTokenModel)).all():
            user = db.get(UserModel, row.user_id)
            if user.email == "a@exemplo.com":
                row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                user.password_changed_at = datetime.now(UTC) + timedelta(seconds=5)
        db.commit()

    for token in (expired["refresh_token"], stale["refresh_token"], "nope"):
        response = client.post("/auth/refresh", json={"refresh_token": token})
        assert response.status_code == 401


def test_refresh_is_refused_for_a_banned_account(review_client) -> None:
    client, session_factory = review_client
    session = _login(client)
    with session_factory() as db:
        user = db.scalar(select(UserModel).where(UserModel.email == "ana@exemplo.com"))
        user.banned_at = datetime.now(UTC)
        db.commit()

    response = client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Account is banned or suspended"}


def test_deleting_the_account_revokes_its_refresh_tokens(review_client) -> None:
    client, _ = review_client
    session = _login(client)
    headers = {"Authorization": f"Bearer {session['access_token']}"}

    deleted = client.request(
        "DELETE", "/users/me", json={"password": PASSWORD}, headers=headers
    )
    refresh = client.post(
        "/auth/refresh", json={"refresh_token": session["refresh_token"]}
    )

    assert deleted.status_code == 204
    assert refresh.status_code == 401
