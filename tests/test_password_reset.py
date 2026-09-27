from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import PasswordResetTokenModel, UserModel
from app.main import app


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


def create_user(email: str) -> UUID:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        user = UserModel(
            user_type=UserTypeEnum.PERSONAL,
            email=email,
            password_hash="unused-test-password-hash",
        )
        db.add(user)
        db.commit()
        return user.user_id
    finally:
        db_generator.close()


def get_password_reset_tokens() -> list[PasswordResetTokenModel]:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        return list(db.scalars(select(PasswordResetTokenModel)))
    finally:
        db_generator.close()


def test_request_for_existing_email_returns_202_and_creates_token(
    client: TestClient,
) -> None:
    user_id = create_user("existing-reset@hangy.com")

    response = client.post(
        "/auth/password-reset/request",
        json={"email": "existing-reset@hangy.com"},
    )

    assert response.status_code == 202
    assert response.content == b""
    tokens = get_password_reset_tokens()
    assert len(tokens) == 1
    assert tokens[0].user_id == user_id
    assert tokens[0].code_hash


def test_request_for_unknown_email_returns_202_without_token(
    client: TestClient,
) -> None:
    response = client.post(
        "/auth/password-reset/request",
        json={"email": "unknown-reset@hangy.com"},
    )

    assert response.status_code == 202
    assert response.content == b""
    assert get_password_reset_tokens() == []


def test_request_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(
        "/auth/password-reset/request",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422
    assert get_password_reset_tokens() == []


def test_request_rate_limits_repeated_requests(client: TestClient) -> None:
    payload = {"email": "rate-limit-reset@hangy.com"}

    responses = [
        client.post("/auth/password-reset/request", json=payload) for _ in range(4)
    ]

    assert [response.status_code for response in responses] == [202, 202, 202, 429]
    assert responses[-1].json() == {"detail": "Too many reset requests"}
