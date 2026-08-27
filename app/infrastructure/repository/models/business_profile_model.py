from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.user_model import user_follows


class BusinessProfileModel(Base):
    __tablename__ = "business_profile"
    __table_args__ = (
        CheckConstraint(
            "(business_latitude IS NULL) = (business_longitude IS NULL)",
            name="ck_business_profile_coordinates_paired",
        ),
        CheckConstraint(
            "business_latitude BETWEEN -90 AND 90 "
            "AND business_longitude BETWEEN -180 AND 180",
            name="ck_business_profile_coordinates_range",
        ),
        # Supports the bounding box that narrows down a radius search.
        Index(
            "idx_business_profile_coordinates",
            "business_latitude",
            "business_longitude",
        ),
    )

    user_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True
    )
    cnpj = Column(String, unique=True, nullable=False)
    business_name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    business_latitude = Column(Double, nullable=True)
    business_longitude = Column(Double, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("UserModel", back_populates="business_profile")
    followers = relationship(
        "UserModel",
        secondary=user_follows,
        back_populates="followed_businesses",
    )
