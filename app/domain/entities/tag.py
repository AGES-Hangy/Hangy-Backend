from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Tag:
    tag_id: UUID | None
    tag_name: str
    tag_parent_id: UUID | None = None
