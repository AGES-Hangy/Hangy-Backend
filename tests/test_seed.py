from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base
from app.infrastructure.repository.models import TagModel, UserModel
from app.seed import SEED_TAGS, seed_tags, seed_users


def test_seed_users_creates_the_default_users_only_once() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_users(db)
        seed_users(db)

        users = db.scalars(select(UserModel).order_by(UserModel.email)).all()

    assert [user.email for user in users] == ["admin@hangy.com", "user@hangy.com"]
    assert all(user.password_hash for user in users)


def test_seed_tags_creates_the_default_macro_and_micro_tags_only_once() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_tags(db)
        seed_tags(db)

        macros = db.scalars(
            select(TagModel).where(TagModel.tag_parent_id.is_(None))
        ).all()

        assert sorted(macro.tag_name for macro in macros) == sorted(SEED_TAGS)

        for macro in macros:
            micro_names = db.scalars(
                select(TagModel.tag_name).where(TagModel.tag_parent_id == macro.tag_id)
            ).all()
            assert sorted(micro_names) == sorted(SEED_TAGS[macro.tag_name])
