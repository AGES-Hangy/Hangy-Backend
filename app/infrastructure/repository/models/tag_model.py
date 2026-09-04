from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.repository.base import Base


class TagModel(Base):
    __tablename__ = "tag"
    __table_args__ = (Index("ix_tag_tag_parent_id", "tag_parent_id"),)

    tag_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tag_name: Mapped[str] = mapped_column(String(50))
    # A tag without a parent is a macro tag; every level below it is a subtag.
    tag_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tag.tag_id", ondelete="SET NULL")
    )

    parent: Mapped[TagModel | None] = relationship(
        remote_side=[tag_id], back_populates="children"
    )
    children: Mapped[list[TagModel]] = relationship(back_populates="parent")
