from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import relationship

from app.infrastructure.repository.base import Base


class PersonProfileModel(Base):
    __tablename__ = "person_profile"

    user_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True
    )
    cpf = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=False)
    country = Column(String, nullable=False)
    state = Column(String, nullable=False)
    city = Column(String, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("UserModel", back_populates="person_profile")
