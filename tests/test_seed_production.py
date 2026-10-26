from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import seed_production as production
from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.domain.services.auth import password_hash
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    EventModel,
    NotificationModel,
    TagModel,
    UserModel,
    user_tag,
)
from app.main import app

ADMIN_PASSWORD = "production-test-password"


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def test_production_seed_creates_only_the_catalog_and_one_admin(sessions):
    with sessions.begin() as db:
        production.seed_production(db, ADMIN_PASSWORD)

    with sessions() as db:
        users = db.scalars(select(UserModel)).all()
        assert len(users) == 1
        admin = users[0]
        assert admin.user_id == production.ADMIN_ID
        assert admin.email == "admin@hangy.com"
        assert admin.role == UserRoleEnum.ADMIN
        assert admin.user_type == UserTypeEnum.BUSINESS
        assert admin.name == "Admin Hangy"
        assert password_hash.verify(ADMIN_PASSWORD, admin.password_hash)
        assert admin.password_changed_at is not None
        assert admin.accepted_terms_at is not None
        assert admin.accepted_terms_version == "2026-08-01"
        profile = admin.business_profile
        assert profile.cnpj == "11222333000181"
        assert profile.address == "Av. Independência, 100 — Porto Alegre"
        assert profile.business_latitude == -30.0331
        assert profile.business_longitude == -51.23

        macros = db.scalars(
            select(TagModel).where(TagModel.tag_parent_id.is_(None))
        ).all()
        actual = {m.tag_name: sorted(t.tag_name for t in m.children) for m in macros}
        assert actual == {
            name: sorted(children)
            for name, children in production.PRODUCTION_TAGS.items()
        }
        assert len(macros) == 8
        assert db.scalar(select(func.count()).select_from(TagModel)) == 162
        # Identical display names must retain their different parents.
        assert (
            db.scalar(
                select(func.count())
                .select_from(TagModel)
                .where(TagModel.tag_name == "Indie")
            )
            == 2
        )
        assert "Esportes" in actual["Jogos"]
        for model in (EventModel, NotificationModel, user_tag):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_production_admin_can_log_in_and_access_its_business_profile(sessions):
    with sessions.begin() as db:
        production.seed_production(db, ADMIN_PASSWORD)

    def override_get_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/login",
                json={"email": production.ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )
            assert response.status_code == 200
            assert response.json()["user"] == {
                "id": str(production.ADMIN_ID),
                "email": production.ADMIN_EMAIL,
                "user_type": "BUSINESS",
                "business_name": "Admin Hangy",
            }
            profile = client.get(
                "/users/me",
                headers={"Authorization": f"Bearer {response.json()['access_token']}"},
            )
            assert profile.status_code == 200
            assert profile.json()["profile"]["cnpj"] == "11222333000181"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_seed_reuses_tags_and_preserves_existing_data_and_password_changes(sessions):
    with sessions.begin() as db:
        sports = TagModel(tag_name="Esportes")
        db.add(sports)
        db.flush()
        football = TagModel(tag_name="Futebol", tag_parent_id=sports.tag_id)
        custom = TagModel(tag_name="Custom tag", tag_parent_id=sports.tag_id)
        regular = UserModel(
            email="regular@example.com",
            user_type=UserTypeEnum.PERSONAL,
            password_hash="existing-hash",
        )
        db.add_all([football, custom, regular])
        db.flush()
        sports_id, football_id, custom_id = (
            sports.tag_id,
            football.tag_id,
            custom.tag_id,
        )
        regular_id = regular.user_id

    with sessions.begin() as db:
        production.seed_production(db, ADMIN_PASSWORD)
    with sessions.begin() as db:
        admin = db.get(UserModel, production.ADMIN_ID)
        admin.password_hash = password_hash.hash("changed-password")
        admin.password_changed_at = datetime(2026, 10, 24, tzinfo=UTC)
        admin.name = "Edited admin"
        admin.business_profile.address = "Edited address"
        expected_hash = admin.password_hash
        before_tags = set(db.scalars(select(TagModel.tag_id)))
        # Also repair a partially populated catalog on subsequent deployments.
        removed_id = db.scalar(
            select(TagModel.tag_id).where(TagModel.tag_name == "Yoga")
        )
        db.execute(delete(TagModel).where(TagModel.tag_id == removed_id))

    for _ in range(2):
        with sessions.begin() as db:
            production.seed_production(db, "different-bootstrap-password")

    with sessions() as db:
        admin = db.get(UserModel, production.ADMIN_ID)
        assert admin.password_hash == expected_hash
        assert admin.password_changed_at == datetime(2026, 10, 24)
        assert admin.name == "Edited admin"
        assert admin.business_profile.address == "Edited address"
        assert db.get(UserModel, regular_id).role == UserRoleEnum.USER
        assert db.get(UserModel, regular_id).password_hash == "existing-hash"
        after_tags = set(db.scalars(select(TagModel.tag_id)))
        assert after_tags >= before_tags - {removed_id}
        assert {sports_id, football_id, custom_id} <= after_tags
        assert len(after_tags) == 163
        assert db.scalar(select(func.count()).select_from(UserModel)) == 2


@pytest.mark.parametrize("password", ["", "short", " " * 12, "x" * 129])
def test_invalid_password_does_not_create_data_or_expose_the_secret(sessions, password):
    with pytest.raises(production.ProductionSeedError) as error:
        with sessions.begin() as db:
            production.seed_production(db, password)
    assert str(error.value).startswith("PRODUCTION_ADMIN_PASSWORD must contain")
    if password:
        assert password not in str(error.value)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(UserModel)) == 0
        assert db.scalar(select(func.count()).select_from(TagModel)) == 0


@pytest.mark.parametrize(
    "conflict", ["email", "deleted", "demoted", "personal", "profile"]
)
def test_conflicting_accounts_are_not_promoted_or_reactivated(sessions, conflict):
    with sessions.begin() as db:
        production.seed_production(db, ADMIN_PASSWORD)
    with sessions.begin() as db:
        admin = db.get(UserModel, production.ADMIN_ID)
        if conflict == "email":
            admin.email = "renamed@example.com"
            db.add(
                UserModel(
                    user_id=uuid4(),
                    email=production.ADMIN_EMAIL,
                    user_type=UserTypeEnum.BUSINESS,
                    password_hash="existing-hash",
                )
            )
        elif conflict == "deleted":
            admin.deleted_at = datetime.now(UTC)
        elif conflict == "demoted":
            admin.role = UserRoleEnum.USER
        elif conflict == "personal":
            admin.user_type = UserTypeEnum.PERSONAL
        else:
            db.delete(admin.business_profile)

    with pytest.raises(production.ProductionSeedError, match="conflicts"):
        with sessions.begin() as db:
            production.seed_production(db, ADMIN_PASSWORD)


def test_existing_regular_account_with_admin_email_is_not_promoted(sessions):
    with sessions.begin() as db:
        db.add(
            UserModel(
                email=production.ADMIN_EMAIL,
                user_type=UserTypeEnum.BUSINESS,
                password_hash="existing-hash",
            )
        )
    with pytest.raises(production.ProductionSeedError, match="conflicts"):
        with sessions.begin() as db:
            production.seed_production(db, ADMIN_PASSWORD)
    with sessions() as db:
        user = db.scalar(select(UserModel))
        assert user.role == UserRoleEnum.USER
        assert user.password_hash == "existing-hash"
        assert db.scalar(select(func.count()).select_from(TagModel)) == 0


def test_database_failure_rolls_back_tags_and_admin_together(sessions):
    with sessions.begin() as db:
        user = UserModel(
            email="business@example.com",
            user_type=UserTypeEnum.BUSINESS,
            password_hash="existing-hash",
            business_profile=BusinessProfileModel(
                cnpj="11222333000181", address="Existing"
            ),
        )
        db.add(user)
    with pytest.raises(IntegrityError):
        with sessions.begin() as db:
            production.seed_production(db, ADMIN_PASSWORD)
    with sessions() as db:
        assert db.get(UserModel, production.ADMIN_ID) is None
        assert db.scalar(select(func.count()).select_from(TagModel)) == 0
        assert db.scalar(select(func.count()).select_from(UserModel)) == 1


def test_main_uses_its_environment_and_commits(sessions, monkeypatch, capsys):
    monkeypatch.setattr(production, "SessionLocal", sessions)
    monkeypatch.setenv("PRODUCTION_ADMIN_PASSWORD", ADMIN_PASSWORD)
    production.main()
    production.main()
    output = capsys.readouterr().out
    assert ADMIN_PASSWORD not in output
    with sessions() as db:
        assert db.get(UserModel, production.ADMIN_ID).role == UserRoleEnum.ADMIN
        assert db.scalar(select(func.count()).select_from(UserModel)) == 1


def test_main_missing_password_fails_without_data(sessions, monkeypatch):
    monkeypatch.setattr(production, "SessionLocal", sessions)
    monkeypatch.delenv("PRODUCTION_ADMIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="PRODUCTION_ADMIN_PASSWORD"):
        production.main()
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(TagModel)) == 0
