from collections.abc import Collection
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, contains_eager, joinedload

from app.domain.entities import Tag
from app.domain.services import UserNotFoundError, UserTagNotFoundError
from app.infrastructure.repository.models import TagModel, UserModel, user_tag
from app.infrastructure.repository.tag import SqlAlchemyTagRepository


class SqlAlchemyUserTagsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_by_ids(self, tag_ids: Collection[UUID]) -> list[Tag]:
        """A lightweight lookup for validation: no parent join, no ordering."""
        if not tag_ids:
            return []
        models = self.db.scalars(
            select(TagModel).where(TagModel.tag_id.in_(tag_ids))
        ).all()
        return [
            Tag(
                tag_id=model.tag_id,
                tag_name=model.tag_name,
                tag_parent_id=model.tag_parent_id,
            )
            for model in models
        ]

    def list_user_tags(self, user_id: UUID) -> list[Tag]:
        """The user's tags ordered by macro name, then tag name, then id."""
        # A tag without a parent sorts under its own name, so the order does not
        # depend on where each database places NULLs.
        parent = aliased(TagModel)
        models = self.db.scalars(
            select(TagModel)
            .join(user_tag, user_tag.c.tag_id == TagModel.tag_id)
            # The same outer join sorts by the macro name and fills `parent`,
            # so building the entities issues no extra query per tag (no N+1).
            .outerjoin(parent, TagModel.parent)
            .where(user_tag.c.user_id == user_id)
            .options(contains_eager(TagModel.parent.of_type(parent)))
            .order_by(
                func.coalesce(parent.tag_name, TagModel.tag_name),
                TagModel.tag_name,
                TagModel.tag_id,
            )
        ).all()
        return [self._to_entity(model) for model in models]

    def replace_user_tags(self, user_id: UUID, tag_ids: Collection[UUID]) -> list[Tag]:
        user_model = self._get_active_user(user_id)

        if not tag_ids:
            user_model.tags = []
            self.db.commit()
            return []

        models = list(
            self.db.scalars(
                select(TagModel)
                .where(TagModel.tag_id.in_(tag_ids))
                .options(joinedload(TagModel.parent))
                .order_by(TagModel.tag_name)
            ).all()
        )
        # The sole existence check: any id not found here means an unknown or
        # since-deleted tag, since the service only pre-checks tag_type.
        if len(models) != len(tag_ids):
            raise UserTagNotFoundError
        user_model.tags = models

        # Built from `models` before commit: the session expires all
        # attributes on commit (expire_on_commit=True), so building this
        # afterwards — from `models` or from `user_model.tags` alike — would
        # re-fetch every tag one by one instead of reusing the ordered,
        # eager-loaded query above.
        entities = [self._to_entity(model) for model in models]
        self.db.commit()
        return entities

    def _get_active_user(self, user_id: UUID) -> UserModel:
        user_model = self.db.scalar(
            select(UserModel).where(
                UserModel.user_id == user_id,
                UserModel.deleted_at.is_(None),
            )
        )
        if user_model is None:
            raise UserNotFoundError
        return user_model

    @staticmethod
    def _to_entity(model: TagModel) -> Tag:
        return SqlAlchemyTagRepository._to_entity(model, include_parent=True)
