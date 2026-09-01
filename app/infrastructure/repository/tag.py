from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.domain.entities import Tag
from app.domain.enums import TagTypeEnum
from app.infrastructure.repository.models import TagModel


class SqlAlchemyTagRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, tag_id: UUID) -> Tag | None:
        model = self.db.scalar(select(TagModel).where(TagModel.tag_id == tag_id))
        return self._to_entity(model) if model is not None else None

    def list_all(self) -> list[Tag]:
        return self._list(select(TagModel))

    def list_by_type(self, tag_type: TagTypeEnum) -> list[Tag]:
        # A macro tag is exactly a tag without a parent.
        condition = (
            TagModel.tag_parent_id.is_(None)
            if tag_type is TagTypeEnum.MACRO
            else TagModel.tag_parent_id.is_not(None)
        )
        return self._list(select(TagModel).where(condition))

    def list_children(self, parent_id: UUID) -> list[Tag]:
        return self._list(select(TagModel).where(TagModel.tag_parent_id == parent_id))

    def _list(self, statement: Select[tuple[TagModel]]) -> list[Tag]:
        models = self.db.scalars(statement.order_by(TagModel.tag_name)).all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_entity(model: TagModel) -> Tag:
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
        )
