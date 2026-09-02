from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.entities import Tag
from app.domain.enums import TagTypeEnum
from app.infrastructure.repository.models import TagModel


class SqlAlchemyTagRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_tree(self) -> list[Tag]:
        macros = self.db.scalars(
            select(TagModel)
            .where(TagModel.tag_type == TagTypeEnum.MACRO)
            .options(selectinload(TagModel.children))
        ).all()
        return [self._to_entity(macro, include_children=True) for macro in macros]

    @staticmethod
    def _to_entity(model: TagModel, include_children: bool = False) -> Tag:
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_type=model.tag_type,
            tag_parent_id=model.tag_parent_id,
            children=(
                [SqlAlchemyTagRepository._to_entity(child) for child in model.children]
                if include_children
                else []
            ),
        )
