import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Uuid, func
from sqlalchemy.orm import relationship

from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

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

    user_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_type = Column(enum_column(UserTypeEnum), nullable=False)
    role = Column(enum_column(UserRoleEnum), nullable=False, default=UserRoleEnum.USER)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    user_phone = Column(String, nullable=True)
    profile_photo_url = Column(String, nullable=True)
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

    person_profile = relationship(
        "PersonProfileModel", back_populates="user", uselist=False, passive_deletes=True
    )
    business_profile = relationship(
        "BusinessProfileModel",
        back_populates="user",
        uselist=False,
        passive_deletes=True,
    )
    created_events = relationship(
        "EventModel", back_populates="creator", passive_deletes=True
    )
    participations = relationship(
        "EventParticipantModel", back_populates="user", passive_deletes=True
    )
    notifications = relationship(
        "NotificationModel", back_populates="user", passive_deletes=True
    )
    tags = relationship("TagModel", secondary=user_tag)
    followed_businesses = relationship(
        "BusinessProfileModel",
        secondary=user_follows,
        back_populates="followers",
    )
    sent_connections = relationship(
        "UserConnectionModel",
        back_populates="requester",
        foreign_keys="UserConnectionModel.requester_id",
        passive_deletes=True,
    )
    received_connections = relationship(
        "UserConnectionModel",
        back_populates="receiver",
        foreign_keys="UserConnectionModel.receiver_id",
        passive_deletes=True,
    )
    created_reports = relationship(
        "ReportModel",
        back_populates="creator",
        foreign_keys="ReportModel.report_creator_id",
        passive_deletes=True,
    )
    received_reports = relationship(
        "ReportModel",
        back_populates="reported_user",
        foreign_keys="ReportModel.reported_user_id",
        passive_deletes=True,
    )
