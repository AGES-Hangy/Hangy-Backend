from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import Tag
from app.domain.services import UserTagNotFoundError
from app.infrastructure.repository.models import TagModel, UserModel


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

    def replace_user_tags(self, user_id: UUID, tag_ids: Collection[UUID]) -> list[Tag]:
        user_model = self.db.get(UserModel, user_id)
        if user_model is None:
            raise ValueError("An authenticated user must exist")

        if not tag_ids:
            user_model.tags = []
        else:
            models = list(
                self.db.scalars(
                    select(TagModel)
                    .where(TagModel.tag_id.in_(tag_ids))
                    .options(joinedload(TagModel.parent))
                    .order_by(TagModel.tag_name)
                ).all()
            )
            # A tag validated by the service may have been deleted since; catching
            # that here keeps the check and the write from racing against it.
            if len(models) != len(tag_ids):
                raise UserTagNotFoundError
            user_model.tags = models

        self.db.commit()
        return [self._to_entity(model) for model in user_model.tags]

    @staticmethod
    def _to_entity(model: TagModel) -> Tag:
        parent = (
            Tag(tag_id=model.parent.tag_id, tag_name=model.parent.tag_name)
            if model.parent is not None
            else None
        )
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
            parent=parent,
        )
