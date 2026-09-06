"""Import SQLAlchemy models here so Alembic can discover their metadata."""

from app._package_exports import load_child_exports
from app.infrastructure.repository.base import Base as Base

load_child_exports(__name__, globals())
