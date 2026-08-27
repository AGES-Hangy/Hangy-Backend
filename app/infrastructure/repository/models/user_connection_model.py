import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import relationship

from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class UserConnectionModel(Base):
    __tablename__ = "user_connection"

    connection_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    requester_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    receiver_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    status = Column(enum_column(UserConnectionStatusEnum), nullable=False)
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

    requester = relationship(
        "UserModel", back_populates="sent_connections", foreign_keys=[requester_id]
    )
    receiver = relationship(
        "UserModel", back_populates="received_connections", foreign_keys=[receiver_id]
    )
