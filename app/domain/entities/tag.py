from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.domain.enums import TagTypeEnum


@dataclass(frozen=True, slots=True)
class Tag:
    tag_id: UUID | None
    tag_name: str
    tag_parent_id: UUID | None = None
    children: list[Tag] = field(default_factory=list)

    @property
    def tag_type(self) -> TagTypeEnum:
        """Roots of the two-level tree are macro tags; their children are micro."""
        return TagTypeEnum.MACRO if self.tag_parent_id is None else TagTypeEnum.MICRO
