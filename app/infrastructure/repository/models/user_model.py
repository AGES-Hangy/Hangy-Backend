import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum as SQLEnum, Table, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base
from app.domain.enums import UserTypeEnum, UserRoleEnum

user_tag = Table(
    "user_tag",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tag.tag_id", ondelete="CASCADE"), primary_key=True),
)

user_follows = Table(
    "user_follows",
    Base.metadata,
    Column("follower_id", UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True),
    Column("followed_business_id", UUID(as_uuid=True), ForeignKey("business_profile.user_id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

class UserModel(Base):
    __tablename__ = "user"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_type = Column(SQLEnum(UserTypeEnum), nullable=False)
    role = Column(SQLEnum(UserRoleEnum), nullable=False, default=UserRoleEnum.USER)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    user_phone = Column(String, nullable=True)
    profile_photo_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    person_profile = relationship("PersonProfileModel", back_populates="user", uselist=False)
    business_profile = relationship("BusinessProfileModel", back_populates="user", uselist=False)
    created_events = relationship("EventModel", back_populates="creator")
    tags = relationship("TagModel", secondary=user_tag)