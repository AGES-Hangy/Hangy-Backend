import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.domain.enums import EventPrivacyEnum, EventStatusEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

event_tag = Table(
    "event_tag",
    Base.metadata,
    Column(
        "event_id",
        Uuid,
        ForeignKey("event.event_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Uuid, ForeignKey("tag.tag_id", ondelete="CASCADE"), primary_key=True
    ),
)


class EventModel(Base):
    __tablename__ = "event"
    __table_args__ = (
        CheckConstraint(
            "event_latitude BETWEEN -90 AND 90 "
            "AND event_longitude BETWEEN -180 AND 180",
            name="ck_event_coordinates_range",
        ),
        # Supports the bounding box that narrows down a radius search.
        Index("idx_event_coordinates", "event_latitude", "event_longitude"),
    )

    event_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_creator_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    event_title = Column(String, nullable=False)
    event_description = Column(String, nullable=True)
    event_latitude = Column(Double, nullable=False)
    event_longitude = Column(Double, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    max_participants = Column(Integer, nullable=True)
    event_status = Column(enum_column(EventStatusEnum), nullable=False)
    event_privacy = Column(enum_column(EventPrivacyEnum), nullable=False)
    cover_photo_url = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    creator = relationship("UserModel", back_populates="created_events")
    tags = relationship("TagModel", secondary=event_tag)
    participants = relationship(
        "EventParticipantModel", back_populates="event", passive_deletes=True
    )
    invite_links = relationship(
        "EventInviteLinkModel", back_populates="event", passive_deletes=True
    )
    reports = relationship(
        "ReportModel",
        back_populates="reported_event",
        foreign_keys="ReportModel.reported_event_id",
    )
