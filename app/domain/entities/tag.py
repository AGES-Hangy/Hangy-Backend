from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.domain.enums.enums import TagTypeEnum


@dataclass(frozen=True, slots=True)
class Tag:
    tag_id: UUID | None
    tag_name: str
    tag_type: TagTypeEnum
    tag_parent_id: UUID | None = None
    children: list[Tag] = field(default_factory=list)
