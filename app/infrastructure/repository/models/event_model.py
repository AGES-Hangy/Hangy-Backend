import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Enum as SQLEnum, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
from app.infrastructure.repository.base import Base
from app.domain.enums import EventStatusEnum, EventPrivacyEnum

event_tag = Table(
    "event_tag",
    Base.metadata,
    Column("event_id", UUID(as_uuid=True), ForeignKey("event.event_id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tag.tag_id", ondelete="CASCADE"), primary_key=True),
)

class EventModel(Base):
    __tablename__ = "event"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_creator_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id"), nullable=False)
    event_title = Column(String, nullable=False)
    event_description = Column(String, nullable=True)
    event_location = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    max_participants = Column(Integer, nullable=True)
    event_status = Column(SQLEnum(EventStatusEnum), nullable=False) 
    event_privacy = Column(SQLEnum(EventPrivacyEnum), nullable=False)
    cover_photo_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    creator = relationship("UserModel", back_populates="created_events")
    tags = relationship("TagModel", secondary=event_tag)
    participants = relationship("EventParticipantModel", back_populates="event")