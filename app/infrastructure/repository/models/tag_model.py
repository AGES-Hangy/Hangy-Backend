from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import TagTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class TagModel(Base):
    __tablename__ = "tag"
    __table_args__ = (Index("ix_tag_tag_parent_id", "tag_parent_id"),)

    tag_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tag_name: Mapped[str] = mapped_column(String(50))
    tag_type: Mapped[TagTypeEnum] = mapped_column(enum_column(TagTypeEnum))
    # A tag without a parent is a macro tag; every level below it is a subtag.
    # TODO: ondelete="SET NULL" conflita com o CHECK acima se uma macro for
    # deletada (a micro ficaria com tag_type=MICRO e tag_parent_id=NULL).
    # Sem endpoint de delete no MVP isso não estoura, mas revisar quando existir.
    tag_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tag.tag_id", ondelete="SET NULL")
    )

    parent: Mapped[TagModel | None] = relationship(
        remote_side=[tag_id], back_populates="children"
    )
    children: Mapped[list[TagModel]] = relationship(back_populates="parent")
