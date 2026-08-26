import uuid
from sqlalchemy import Column, String, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base
from app.domain.enums import TagTypeEnum

class TagModel(Base):
    __tablename__ = "tag"

    tag_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_name = Column(String, nullable=False)
    tag_type = Column(SQLEnum(TagTypeEnum), nullable=False)
    tag_parent_id = Column(UUID(as_uuid=True), ForeignKey("tag.tag_id", ondelete="SET NULL"), nullable=True)

    parent = relationship("TagModel", remote_side=[tag_id], backref="children")