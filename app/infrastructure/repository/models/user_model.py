from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.business_profile_model import (
        BusinessProfileModel,
    )
    from app.infrastructure.repository.models.event_model import EventModel
    from app.infrastructure.repository.models.event_participant_model import (
        EventParticipantModel,
    )
    from app.infrastructure.repository.models.notification_model import (
        NotificationModel,
    )
    from app.infrastructure.repository.models.person_profile_model import (
        PersonProfileModel,
    )
    from app.infrastructure.repository.models.report_model import ReportModel
    from app.infrastructure.repository.models.tag_model import TagModel
    from app.infrastructure.repository.models.user_connection_model import (
        UserConnectionModel,
    )


user_tag = Table(
    "user_tag",
    Base.metadata,
    Column(
        "user_id",
        Uuid,
        ForeignKey("user.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Uuid, ForeignKey("tag.tag_id", ondelete="CASCADE"), primary_key=True
    ),
)

user_follows = Table(
    "user_follows",
    Base.metadata,
    Column(
        "follower_id",
        Uuid,
        ForeignKey("user.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "followed_business_id",
        Uuid,
        ForeignKey("business_profile.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)


class UserModel(Base):
    __tablename__ = "user"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_type: Mapped[UserTypeEnum] = mapped_column(enum_column(UserTypeEnum))
    role: Mapped[UserRoleEnum] = mapped_column(
        enum_column(UserRoleEnum), default=UserRoleEnum.USER
    )
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Display name and bio are shared by every user type, so they live here
    # instead of being duplicated across person_profile and business_profile.
    name: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    user_phone: Mapped[str | None] = mapped_column(String(20))
    profile_photo_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    person_profile: Mapped[PersonProfileModel | None] = relationship(
        back_populates="user", passive_deletes=True
    )
    business_profile: Mapped[BusinessProfileModel | None] = relationship(
        back_populates="user", passive_deletes=True
    )
    created_events: Mapped[list[EventModel]] = relationship(
        back_populates="creator", passive_deletes=True
    )
    participations: Mapped[list[EventParticipantModel]] = relationship(
        back_populates="user", passive_deletes=True
    )
    notifications: Mapped[list[NotificationModel]] = relationship(
        back_populates="user", passive_deletes=True
    )
    tags: Mapped[list[TagModel]] = relationship(secondary=user_tag)
    followed_businesses: Mapped[list[BusinessProfileModel]] = relationship(
        secondary=user_follows,
        back_populates="followers",
    )
    sent_connections: Mapped[list[UserConnectionModel]] = relationship(
        back_populates="requester",
        foreign_keys="UserConnectionModel.requester_id",
        passive_deletes=True,
    )
    received_connections: Mapped[list[UserConnectionModel]] = relationship(
        back_populates="receiver",
        foreign_keys="UserConnectionModel.receiver_id",
        passive_deletes=True,
    )
    created_reports: Mapped[list[ReportModel]] = relationship(
        back_populates="creator",
        foreign_keys="ReportModel.report_creator_id",
        passive_deletes=True,
    )
    received_reports: Mapped[list[ReportModel]] = relationship(
        back_populates="reported_user",
        foreign_keys="ReportModel.reported_user_id",
        passive_deletes=True,
    )
