from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import PasswordResetTokenModel, UserModel
from app.main import app

CONFIRM_URL = "/auth/password-reset/confirm"
USER_EMAIL = "reset-confirm@hangy.com"
OLD_PASSWORD = "old-strong-password"
NEW_PASSWORD = "outra-senha-forte"
INVALID_TOKEN_DETAIL = {"detail": "Invalid or expired reset token"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@contextmanager
def db_session() -> Iterator[Session]:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        yield db
    finally:
        db_generator.close()


def register_user(client: TestClient) -> UUID:
    response = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": USER_EMAIL,
            "password": OLD_PASSWORD,
            "name": "Felipe Souza",
            "cpf": "52998224725",
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["user"]["id"])


def create_reset_token_row(
    user_id: UUID,
    *,
    verified: bool = True,
    used: bool = False,
) -> UUID:
    now = datetime.now(UTC)
    token_id = uuid4()
    with db_session() as db:
        db.add(
            PasswordResetTokenModel(
                token_id=token_id,
                user_id=user_id,
                code_hash="unused-test-code-hash",
                attempts=0,
                verified_at=now if verified else None,
                expires_at=now + timedelta(minutes=15),
                used_at=now if used else None,
            )
        )
        db.commit()
    return token_id


def make_reset_token(
    token_id: UUID,
    *,
    scope: str = "password_reset",
    expires_in: timedelta = timedelta(minutes=10),
) -> str:
    """Mimics what POST /auth/password-reset/verify emits."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "token_id": str(token_id),
            "scope": scope,
            "iat": now,
            "exp": now + expires_in,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def confirm(client: TestClient, reset_token: str, new_password: str = NEW_PASSWORD):
    return client.post(
        CONFIRM_URL,
        json={"reset_token": reset_token, "new_password": new_password},
    )


def login(client: TestClient, password: str):
    return client.post("/auth/login", json={"email": USER_EMAIL, "password": password})


def get_user(user_id: UUID) -> UserModel:
    with db_session() as db:
        user = db.scalar(select(UserModel).where(UserModel.user_id == user_id))
        assert user is not None
        return user


def get_token_row(token_id: UUID) -> PasswordResetTokenModel:
    with db_session() as db:
        row = db.scalar(
            select(PasswordResetTokenModel).where(
                PasswordResetTokenModel.token_id == token_id
            )
        )
        assert row is not None
        return row


def test_valid_reset_token_changes_password_and_returns_204(
    client: TestClient,
) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)

    response = confirm(client, make_reset_token(token_id))

    assert response.status_code == 204
    assert response.content == b""
    assert login(client, NEW_PASSWORD).status_code == 200
    assert get_token_row(token_id).used_at is not None
    assert get_user(user_id).password_changed_at is not None


def test_old_password_stops_working_after_reset(client: TestClient) -> None:
    user_id = register_user(client)
    assert login(client, OLD_PASSWORD).status_code == 200
    token_id = create_reset_token_row(user_id)

    confirm(client, make_reset_token(token_id))

    assert login(client, OLD_PASSWORD).status_code == 401


def test_expired_reset_token_is_rejected(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)

    response = confirm(
        client, make_reset_token(token_id, expires_in=timedelta(minutes=-1))
    )

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN_DETAIL
    assert login(client, OLD_PASSWORD).status_code == 200


def test_reset_token_cannot_be_used_twice(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)
    reset_token = make_reset_token(token_id)

    first = confirm(client, reset_token)
    second = confirm(client, reset_token, new_password="another-strong-one")

    assert first.status_code == 204
    assert second.status_code == 400
    assert second.json() == INVALID_TOKEN_DETAIL
    assert login(client, NEW_PASSWORD).status_code == 200
    assert login(client, "another-strong-one").status_code == 401


def test_reset_token_already_marked_as_used_is_rejected(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id, used=True)

    response = confirm(client, make_reset_token(token_id))

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN_DETAIL
    assert login(client, OLD_PASSWORD).status_code == 200


def test_session_jwt_is_rejected_as_reset_token(client: TestClient) -> None:
    register_user(client)
    session_token = login(client, OLD_PASSWORD).json()["access_token"]

    response = confirm(client, session_token)

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN_DETAIL


def test_reset_token_with_another_scope_is_rejected(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)

    response = confirm(client, make_reset_token(token_id, scope="email_change"))

    assert response.status_code == 400
    assert login(client, OLD_PASSWORD).status_code == 200


def test_reset_token_with_bad_signature_is_rejected(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)
    forged = jwt.encode(
        {
            "token_id": str(token_id),
            "scope": "password_reset",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        "not-the-real-secret-key-with-enough-length",
        algorithm=settings.jwt_algorithm,
    )

    response = confirm(client, forged)

    assert response.status_code == 400
    assert login(client, OLD_PASSWORD).status_code == 200


def test_garbage_reset_token_is_rejected(client: TestClient) -> None:
    response = confirm(client, "not-a-jwt")

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN_DETAIL


def test_reset_token_for_unknown_token_id_is_rejected(client: TestClient) -> None:
    register_user(client)

    response = confirm(client, make_reset_token(uuid4()))

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN_DETAIL


def test_valid_jwt_for_unverified_token_row_is_rejected(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id, verified=False)

    response = confirm(client, make_reset_token(token_id))

    assert response.status_code == 400
    assert response.json() == INVALID_TOKEN_DETAIL
    assert login(client, OLD_PASSWORD).status_code == 200
    assert get_token_row(token_id).used_at is None


def test_reset_for_deleted_account_is_rejected(client: TestClient) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)
    with db_session() as db:
        user = db.scalar(select(UserModel).where(UserModel.user_id == user_id))
        assert user is not None
        user.deleted_at = datetime.now(UTC)
        db.commit()

    response = confirm(client, make_reset_token(token_id))

    assert response.status_code == 400
    assert get_token_row(token_id).used_at is None


def test_password_below_minimum_returns_422_and_keeps_token_usable(
    client: TestClient,
) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)
    reset_token = make_reset_token(token_id)

    response = confirm(client, reset_token, new_password="short")

    assert response.status_code == 422
    assert get_token_row(token_id).used_at is None
    assert confirm(client, reset_token).status_code == 204


def test_legacy_email_and_code_fields_are_rejected_with_422(
    client: TestClient,
) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)

    response = client.post(
        CONFIRM_URL,
        json={
            "reset_token": make_reset_token(token_id),
            "new_password": NEW_PASSWORD,
            "email": USER_EMAIL,
            "code": "123456",
        },
    )

    assert response.status_code == 422
    assert get_token_row(token_id).used_at is None


def test_session_jwt_issued_before_reset_is_rejected_afterwards(
    client: TestClient,
) -> None:
    user_id = register_user(client)
    # Registration stamps password_changed_at with "now", and the check
    # compares whole seconds. Backdate it and mint the session token in the
    # past so it sits clearly between registration and the reset.
    with db_session() as db:
        user = db.scalar(select(UserModel).where(UserModel.user_id == user_id))
        assert user is not None
        user.password_changed_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    issued_at = datetime.now(UTC) - timedelta(minutes=1)
    old_session_token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": issued_at + timedelta(minutes=30),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    headers = {"Authorization": f"Bearer {old_session_token}"}
    assert client.get("/users/me", headers=headers).status_code == 200
    token_id = create_reset_token_row(user_id)

    confirm(client, make_reset_token(token_id))

    assert client.get("/users/me", headers=headers).status_code == 401


def test_reset_token_cannot_authenticate_as_session_token(
    client: TestClient,
) -> None:
    user_id = register_user(client)
    token_id = create_reset_token_row(user_id)

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {make_reset_token(token_id)}"},
    )

    assert response.status_code == 401
