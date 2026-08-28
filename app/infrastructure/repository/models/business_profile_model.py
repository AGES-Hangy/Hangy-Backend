from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.user_model import user_follows

if TYPE_CHECKING:
    from app.infrastructure.repository.models.user_model import UserModel


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

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True
    )
    # Digits only, no punctuation.
    cnpj: Mapped[str] = mapped_column(String(14), unique=True)
    business_latitude: Mapped[float | None] = mapped_column(Double)
    business_longitude: Mapped[float | None] = mapped_column(Double)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[UserModel] = relationship(back_populates="business_profile")
    followers: Mapped[list[UserModel]] = relationship(
        secondary=user_follows,
        back_populates="followed_businesses",
    )
