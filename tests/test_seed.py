from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base
from app.infrastructure.repository.models import UserModel
from app.seed import seed_users


def test_seed_users_creates_the_default_users_only_once() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_users(db)
        seed_users(db)

        users = db.scalars(select(UserModel).order_by(UserModel.email)).all()

    assert [user.email for user in users] == ["admin@hangy.com", "user@hangy.com"]
    assert all(user.password_hash for user in users)
