from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.domain.entities import Tag
from app.domain.enums import TagTypeEnum
from app.infrastructure.repository.models import TagModel, event_tag, user_tag


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

    def get_tree(self) -> list[Tag]:
        # A single query with the children eagerly loaded avoids N+1 calls
        # when building the two-level tree.
        macros = self.db.scalars(
            select(TagModel)
            .where(TagModel.tag_parent_id.is_(None))
            .options(selectinload(TagModel.children))
            .order_by(TagModel.tag_name)
        ).all()
        return [self._to_tree_entity(macro) for macro in macros]

    def name_exists(
        self, name: str, parent_id: UUID | None, *, exclude_tag_id: UUID | None = None
    ) -> bool:
        """Whether a tag with this name already exists at the given level."""
        level = (
            TagModel.tag_parent_id.is_(None)
            if parent_id is None
            else TagModel.tag_parent_id == parent_id
        )
        statement = select(TagModel.tag_id).where(TagModel.tag_name == name, level)
        if exclude_tag_id is not None:
            statement = statement.where(TagModel.tag_id != exclude_tag_id)
        return self.db.scalar(statement.limit(1)) is not None

    def create(self, tag: Tag) -> Tag:
        model = TagModel(tag_name=tag.tag_name, tag_parent_id=tag.tag_parent_id)
        self.db.add(model)
        # Flush only: the caller (AdminTagsService.create_tag) commits after
        # also recording the audit row, so both land in one transaction.
        self.db.flush()
        return self._to_entity(model)

    def rename(self, tag_id: UUID, name: str) -> Tag:
        model = self.db.get(TagModel, tag_id)
        assert model is not None  # service already verified existence
        model.tag_name = name
        # Flush only: the caller commits, so the rename and its audit row are
        # one transaction (see SqlAlchemyAuditRepository.add).
        self.db.flush()
        return self._to_entity(model)

    def count_children(self, tag_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(TagModel)
            .where(TagModel.tag_parent_id == tag_id)
        )
        return self.db.scalar(statement) or 0

    def count_usage(self, tag_id: UUID) -> int:
        user_count = self.db.scalar(
            select(func.count())
            .select_from(user_tag)
            .where(user_tag.c.tag_id == tag_id)
        )
        event_count = self.db.scalar(
            select(func.count())
            .select_from(event_tag)
            .where(event_tag.c.tag_id == tag_id)
        )
        return (user_count or 0) + (event_count or 0)

    def delete(self, tag_id: UUID) -> None:
        # Explicitly remove links as well as relying on ON DELETE CASCADE. This
        # keeps the behavior correct in SQLite tests and other DB configurations
        # where foreign-key cascades may not be enabled.
        self.db.execute(delete(user_tag).where(user_tag.c.tag_id == tag_id))
        self.db.execute(delete(event_tag).where(event_tag.c.tag_id == tag_id))
        self.db.execute(delete(TagModel).where(TagModel.tag_id == tag_id))
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def _list(self, statement: Select[tuple[TagModel]]) -> list[Tag]:
        models = self.db.scalars(statement.order_by(TagModel.tag_name)).all()
        return [self._to_entity(model) for model in models]

    @staticmethod
    def _to_entity(model: TagModel, *, include_parent: bool = False) -> Tag:
        parent = None
        if include_parent and model.parent is not None:
            parent = Tag(tag_id=model.parent.tag_id, tag_name=model.parent.tag_name)
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
            parent=parent,
        )

    @staticmethod
    def _to_tree_entity(model: TagModel) -> Tag:
        children = sorted(model.children, key=lambda child: child.tag_name)
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
            children=[SqlAlchemyTagRepository._to_entity(child) for child in children],
        )
