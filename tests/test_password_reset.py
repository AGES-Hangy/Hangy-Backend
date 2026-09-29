from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import UserTypeEnum
from app.domain.services.password_reset import password_hash
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


VERIFY_URL = "/auth/password-reset/verify"
RESET_EMAIL = "verify-reset@hangy.com"
RESET_CODE = "483920"


def create_reset_token(
    user_id: UUID,
    code: str = RESET_CODE,
    *,
    expires_in: timedelta = timedelta(minutes=15),
    attempts: int = 0,
    verified_at: datetime | None = None,
    used_at: datetime | None = None,
) -> UUID:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        token = PasswordResetTokenModel(
            token_id=uuid4(),
            user_id=user_id,
            code_hash=password_hash.hash(code),
            attempts=attempts,
            verified_at=verified_at,
            expires_at=datetime.now(UTC) + expires_in,
            used_at=used_at,
            created_at=datetime.now(UTC),
        )
        db.add(token)
        db.commit()
        return token.token_id
    finally:
        db_generator.close()


def verify(client: TestClient, code: str = RESET_CODE):
    return client.post(VERIFY_URL, json={"email": RESET_EMAIL, "code": code})


def test_verify_correct_code_returns_200_with_reset_token(client: TestClient) -> None:
    user_id = create_user(RESET_EMAIL)
    token_id = create_reset_token(user_id)

    response = verify(client)

    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == 600
    payload = jwt.decode(
        body["reset_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["scope"] == "password_reset"
    assert payload["token_id"] == str(token_id)
    token = get_password_reset_tokens()[0]
    assert token.verified_at is not None
    assert token.used_at is None


def test_verify_wrong_code_returns_400_and_increments_attempts(
    client: TestClient,
) -> None:
    create_reset_token(create_user(RESET_EMAIL))

    response = verify(client, "000000")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired code"}
    assert get_password_reset_tokens()[0].attempts == 1


def test_verify_unknown_email_returns_400(client: TestClient) -> None:
    response = verify(client)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired code"}


def test_verify_expired_code_returns_400(client: TestClient) -> None:
    create_reset_token(create_user(RESET_EMAIL), expires_in=timedelta(minutes=-1))

    response = verify(client)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired code"}


def test_verify_sixth_wrong_attempt_returns_429_even_with_correct_code(
    client: TestClient,
) -> None:
    create_reset_token(create_user(RESET_EMAIL))

    wrong = [verify(client, "000000").status_code for _ in range(5)]
    response = verify(client)

    assert wrong == [400] * 5
    assert response.status_code == 429
    assert response.json() == {"detail": "Too many attempts"}
    assert get_password_reset_tokens()[0].verified_at is None


def test_verify_already_verified_code_still_works_and_issues_new_token(
    client: TestClient,
) -> None:
    create_reset_token(create_user(RESET_EMAIL))

    first = verify(client)
    second = verify(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["reset_token"] != second.json()["reset_token"]


def test_verify_already_used_code_returns_400(client: TestClient) -> None:
    now = datetime.now(UTC)
    create_reset_token(create_user(RESET_EMAIL), verified_at=now, used_at=now)

    response = verify(client)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired code"}


def test_verify_rejects_invalid_payload(client: TestClient) -> None:
    response = client.post(VERIFY_URL, json={"email": RESET_EMAIL, "code": "12ab"})

    assert response.status_code == 422


def test_reset_token_is_not_accepted_as_bearer_token(client: TestClient) -> None:
    create_reset_token(create_user(RESET_EMAIL))
    reset_token = verify(client).json()["reset_token"]

    response = client.get(
        "/users/me", headers={"Authorization": f"Bearer {reset_token}"}
    )

    assert response.status_code == 401
