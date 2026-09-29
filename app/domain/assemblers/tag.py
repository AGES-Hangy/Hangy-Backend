from app.domain.entities import Tag
from app.presentation.dtos import (
    TagLeafOutput,
    TagNodeOutput,
    TagOutput,
    TagParentOutput,
    UserTagOutput,
    UserTagsOutput,
)


class TagAssembler:
    """Build tag response DTOs from domain entities."""

    @staticmethod
    def to_dto(tag: Tag) -> TagOutput:
        if tag.tag_id is None:
            raise ValueError("A persisted tag must have an id")
        return TagOutput(
            id=tag.tag_id,
            name=tag.tag_name,
            type=tag.tag_type,
            parent_id=tag.tag_parent_id,
        )

    @staticmethod
    def to_dtos(tags: list[Tag]) -> list[TagOutput]:
        return [TagAssembler.to_dto(tag) for tag in tags]

    @staticmethod
    def to_tree_dto(tags: list[Tag]) -> list[TagNodeOutput]:
        return [TagAssembler._to_node_dto(tag) for tag in tags]

    @staticmethod
    def _to_node_dto(tag: Tag) -> TagNodeOutput:
        return TagNodeOutput(
            id=tag.tag_id,
            name=tag.tag_name,
            type="MACRO",
            children=[
                TagLeafOutput(id=child.tag_id, name=child.tag_name, type="MICRO")
                for child in tag.children
            ],
        )

    @staticmethod
    def to_user_tags_dto(tags: list[Tag]) -> UserTagsOutput:
        return UserTagsOutput(tags=[TagAssembler._to_user_tag_dto(tag) for tag in tags])

    @staticmethod
    def _to_user_tag_dto(tag: Tag) -> UserTagOutput:
        parent = (
            TagParentOutput(id=tag.parent.tag_id, name=tag.parent.tag_name)
            if tag.parent is not None
            else None
        )
        return UserTagOutput(id=tag.tag_id, name=tag.tag_name, parent=parent)
