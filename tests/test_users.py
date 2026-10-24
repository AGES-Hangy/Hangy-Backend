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
from app.infrastructure.repository.models.user_block_model import UserBlockModel
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

    db_session.add(UserBlockModel(blocker_id=target_id, blocked_id=viewer_id))
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


def auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": str(user_id)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def add_connection(
    db: Session,
    requester_id: uuid.UUID,
    receiver_id: uuid.UUID,
    status: UserConnectionStatusEnum,
) -> uuid.UUID:
    connection = UserConnectionModel(
        requester_id=requester_id, receiver_id=receiver_id, status=status
    )
    db.add(connection)
    db.commit()
    return connection.connection_id


def test_profile_pending_request_sent_by_viewer(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")
    connection_id = add_connection(
        db_session, viewer_id, target_id, UserConnectionStatusEnum.PENDING
    )

    response = client.get(f"/users/{target_id}", headers=auth_headers(viewer_id))

    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] == "PENDING"
    assert data["connection_id"] == str(connection_id)
    assert data["connection_direction"] == "SENT"
    assert data["followers_count"] is None


def test_profile_pending_request_received_by_viewer(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")
    connection_id = add_connection(
        db_session, target_id, viewer_id, UserConnectionStatusEnum.PENDING
    )

    response = client.get(f"/users/{target_id}", headers=auth_headers(viewer_id))

    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] == "PENDING"
    assert data["connection_id"] == str(connection_id)
    assert data["connection_direction"] == "RECEIVED"


@pytest.mark.parametrize("viewer_is_requester", [True, False])
def test_profile_confirmed_connection_has_id_and_no_direction(
    client: TestClient, db_session: Session, viewer_is_requester: bool
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")
    requester_id, receiver_id = (
        (viewer_id, target_id) if viewer_is_requester else (target_id, viewer_id)
    )
    connection_id = add_connection(
        db_session, requester_id, receiver_id, UserConnectionStatusEnum.CONFIRMED
    )

    response = client.get(f"/users/{target_id}", headers=auth_headers(viewer_id))

    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] == "CONFIRMED"
    assert data["connection_id"] == str(connection_id)
    assert data["connection_direction"] is None


def test_profile_without_connection_has_null_fields(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")

    response = client.get(f"/users/{target_id}", headers=auth_headers(viewer_id))

    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] is None
    assert data["connection_id"] is None
    assert data["connection_direction"] is None


def test_profile_rejected_connection_does_not_expose_id(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")
    add_connection(db_session, viewer_id, target_id, UserConnectionStatusEnum.REJECTED)

    response = client.get(f"/users/{target_id}", headers=auth_headers(viewer_id))

    assert response.status_code == 200
    data = response.json()
    assert data["connection_status"] == "REJECTED"
    assert data["connection_id"] is None
    assert data["connection_direction"] is None


def test_profile_own_profile_has_no_connection_fields(
    client: TestClient, db_session: Session
) -> None:
    user_id = create_user(db_session, "PERSONAL", "me@test.com", "Me")

    response = client.get(f"/users/{user_id}", headers=auth_headers(user_id))

    assert response.status_code == 200
    data = response.json()
    assert data["connection_id"] is None
    assert data["connection_direction"] is None
    assert data["followers_count"] is None


@pytest.mark.parametrize("followers", [0, 1, 3])
def test_business_profile_followers_count(
    client: TestClient, db_session: Session, followers: int
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    business_id = create_user(db_session, "BUSINESS", "biz@test.com", "Biz")
    follower_ids = [
        create_user(db_session, "PERSONAL", f"f{i}@test.com", f"F{i}")
        for i in range(followers)
    ]
    for follower_id in follower_ids:
        db_session.execute(
            insert(user_follows).values(
                follower_id=follower_id, followed_business_id=business_id
            )
        )
    db_session.commit()

    response = client.get(f"/users/{business_id}", headers=auth_headers(viewer_id))

    assert response.status_code == 200
    data = response.json()
    assert data["followers_count"] == followers
    assert data["is_following"] is False
    assert data["connections_count"] == followers
    assert data["connection_id"] is None
    assert data["connection_direction"] is None


def test_business_profile_followers_count_includes_viewer(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    other_id = create_user(db_session, "PERSONAL", "other@test.com", "Other")
    business_id = create_user(db_session, "BUSINESS", "biz@test.com", "Biz")
    for follower_id in (viewer_id, other_id):
        db_session.execute(
            insert(user_follows).values(
                follower_id=follower_id, followed_business_id=business_id
            )
        )
    db_session.commit()

    response = client.get(f"/users/{business_id}", headers=auth_headers(viewer_id))

    data = response.json()
    assert data["followers_count"] == 2
    assert data["is_following"] is True


def test_profile_existing_fields_are_unchanged(
    client: TestClient, db_session: Session
) -> None:
    viewer_id = create_user(db_session, "PERSONAL", "viewer@test.com", "Viewer")
    target_id = create_user(db_session, "PERSONAL", "target@test.com", "Target")
    other_id = create_user(db_session, "PERSONAL", "other@test.com", "Other")
    add_connection(db_session, viewer_id, target_id, UserConnectionStatusEnum.PENDING)
    add_connection(db_session, other_id, target_id, UserConnectionStatusEnum.CONFIRMED)

    response = client.get(f"/users/{target_id}", headers=auth_headers(viewer_id))

    data = response.json()
    assert set(data) >= {
        "id",
        "user_type",
        "name",
        "description",
        "photo_url",
        "tags",
        "connection_status",
        "is_following",
        "connections_count",
    }
    assert data["id"] == str(target_id)
    assert data["user_type"] == "PERSONAL"
    assert data["name"] == "Target"
    assert data["connection_status"] == "PENDING"
    assert data["is_following"] is False
    assert data["connections_count"] == 1
