import uuid
from collections.abc import Iterator
from datetime import UTC

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    PersonProfileModel,
    UserConnectionModel,
    UserModel,
    user_follows,
)
from app.main import app

USER_EMAIL = "test@hangy.com"
USER_PASSWORD = "strong-password"


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


@pytest.fixture
def db_session() -> Iterator[Session]:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        yield db
    finally:
        db_generator.close()


def create_user(
    db: Session,
    user_type: str = "PERSONAL",
    email: str = "test@test.com",
    name: str = "Test User",
) -> uuid.UUID:
    user = UserModel(
        user_type=user_type,
        email=email,
        password_hash="hash",
        name=name,
    )
    db.add(user)
    db.commit()

    from datetime import date

    if user_type == "PERSONAL":
        person = PersonProfileModel(
            user_id=user.user_id,
            cpf=str(uuid.uuid4())[:11],
            date_of_birth=date(2000, 1, 1),
            state="RS",
            city="Porto Alegre",
        )
        db.add(person)
    else:
        business = BusinessProfileModel(
            user_id=user.user_id,
            cnpj=str(uuid.uuid4())[:14],
            address="Street A",
        )
        db.add(business)
    db.commit()
    return user.user_id


def test_get_personal_profile_connection_status(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")

    db_session.add(
        UserConnectionModel(
            requester_id=viewer_id,
            receiver_id=target_id,
            status=UserConnectionStatusEnum.PENDING,
        )
    )
    db_session.commit()

    # We need to authenticate viewer to access /users/{user_id}
    # For testing, we can mock the auth
    # Let's just create an access token using AuthService
    import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": str(viewer_id)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        f"/users/{target_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] == "PENDING"
    assert data["is_following"] is False
    assert data["connections_count"] == 0
    assert "email" not in data


def test_get_business_profile_is_following(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer2@test.com", "Viewer")
    target_id = create_user(
        db_session, "BUSINESS", "target2@test.com", "Target Business"
    )

    db_session.execute(
        insert(user_follows).values(
            follower_id=viewer_id, followed_business_id=target_id
        )
    )
    db_session.commit()

    import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": str(viewer_id)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        f"/users/{target_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] is None
    assert data["is_following"] is True
    assert data["connections_count"] == 1


def test_get_profile_returns_404_if_deleted(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer3@test.com", "Viewer")
    target_id = create_user(
        db_session, "PERSONAL", "target3@test.com", "Target Deleted"
    )

    from datetime import datetime

    db_session.query(UserModel).filter_by(user_id=target_id).update(
        {"deleted_at": datetime.now(UTC)}
    )
    db_session.commit()

    import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": str(viewer_id)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        f"/users/{target_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_get_profile_returns_404_if_blocked(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer4@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target4@test.com", "Target")

    # Mocking block via table clause
    from sqlalchemy import Uuid, column, insert, table

    user_block = table(
        "user_block",
        column("blocker_id", Uuid),
        column("blocked_id", Uuid),
    )

    # We must ensure the table exists in sqlite for testing, but it's not created by Base.metadata because it's not a model
    try:
        from sqlalchemy import Column, MetaData, Table

        metadata = MetaData()
        Table(
            "user_block",
            metadata,
            Column("blocker_id", Uuid),
            Column("blocked_id", Uuid),
        )
        metadata.create_all(db_session.bind)
        db_session.execute(
            insert(user_block).values(blocker_id=target_id, blocked_id=viewer_id)
        )
        db_session.commit()
    except Exception:
        pass

    import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": str(viewer_id)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        f"/users/{target_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
