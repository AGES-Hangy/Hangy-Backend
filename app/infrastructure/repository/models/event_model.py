from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    Table,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import EventPrivacyEnum, EventStatusEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_invite_link_model import (
        EventInviteLinkModel,
    )
    from app.infrastructure.repository.models.event_participant_model import (
        EventParticipantModel,
    )
    from app.infrastructure.repository.models.report_model import ReportModel
    from app.infrastructure.repository.models.tag_model import TagModel
    from app.infrastructure.repository.models.user_model import UserModel


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

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    event_title: Mapped[str] = mapped_column(String(50))
    event_description: Mapped[str | None] = mapped_column(String(1000))
    event_latitude: Mapped[float] = mapped_column(Double)
    event_longitude: Mapped[float] = mapped_column(Double)
    # Coordinates alone cannot render "Parcao" on the event card.
    location_name: Mapped[str | None] = mapped_column(String(120))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_participants: Mapped[int | None]
    event_status: Mapped[EventStatusEnum] = mapped_column(enum_column(EventStatusEnum))
    event_privacy: Mapped[EventPrivacyEnum] = mapped_column(
        enum_column(EventPrivacyEnum)
    )
    cover_photo_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    creator: Mapped[UserModel] = relationship(back_populates="created_events")
    tags: Mapped[list[TagModel]] = relationship(secondary=event_tag)
    participants: Mapped[list[EventParticipantModel]] = relationship(
        back_populates="event", passive_deletes=True
    )
    invite_links: Mapped[list[EventInviteLinkModel]] = relationship(
        back_populates="event", passive_deletes=True
    )
    reports: Mapped[list[ReportModel]] = relationship(
        back_populates="reported_event",
        foreign_keys="ReportModel.reported_event_id",
    )
