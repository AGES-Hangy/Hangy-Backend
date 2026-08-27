import uuid

from sqlalchemy import Column, ForeignKey, String, Uuid
from sqlalchemy.orm import relationship

from app.domain.enums import TagTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class TagModel(Base):
    __tablename__ = "tag"

    tag_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tag_name = Column(String, nullable=False)
    tag_type = Column(enum_column(TagTypeEnum), nullable=False)
    tag_parent_id = Column(
        Uuid, ForeignKey("tag.tag_id", ondelete="SET NULL"), nullable=True
    )

    parent = relationship("TagModel", remote_side=[tag_id], back_populates="children")
    children = relationship("TagModel", back_populates="parent")
