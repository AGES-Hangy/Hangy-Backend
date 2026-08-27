import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import relationship

from app.infrastructure.repository.base import Base


class EventInviteLinkModel(Base):
    __tablename__ = "event_invite_link"

    invite_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id = Column(
        Uuid, ForeignKey("event.event_id", ondelete="CASCADE"), nullable=False
    )
    token = Column(String, unique=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)

    event = relationship("EventModel", back_populates="invite_links")
