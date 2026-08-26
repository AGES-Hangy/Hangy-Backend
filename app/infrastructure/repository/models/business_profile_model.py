from datetime import datetime, timezone
from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
from app.infrastructure.repository.base import Base

class BusinessProfileModel(Base):
    __tablename__ = "business_profile"

    user_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True)
    cnpj = Column(String, unique=True, nullable=False)
    business_name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    business_location = Column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    user = relationship("UserModel", back_populates="business_profile")