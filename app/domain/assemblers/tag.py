from app.domain.entities import Tag
from app.presentation.dtos import TagOutput


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
