from app.domain.entities import Tag
from app.presentation.dtos import TagLeafOutput, TagNodeOutput


class TagAssembler:
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
