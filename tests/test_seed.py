from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base
from app.infrastructure.repository.models import TagModel, UserModel
from app.seed import SEED_MACRO_TAGS, seed_tags, seed_users


def test_seed_users_creates_the_default_users_only_once() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_users(db)
        seed_users(db)

        users = db.scalars(select(UserModel).order_by(UserModel.email)).all()

    assert [user.email for user in users] == ["admin@hangy.com", "user@hangy.com"]
    assert all(user.password_hash for user in users)


def test_seed_tags_creates_the_default_macro_tags_only_once() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_tags(db)
        seed_tags(db)

        tags = db.scalars(
            select(TagModel).where(TagModel.tag_parent_id.is_(None))
        ).all()

    assert sorted(tag.tag_name for tag in tags) == sorted(SEED_MACRO_TAGS)
