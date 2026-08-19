"""Import SQLAlchemy models here so Alembic can discover their metadata."""

from app.infrastructure.repository.models.user import UserModel

__all__ = ["UserModel"]
