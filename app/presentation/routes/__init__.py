"""FastAPI route modules."""

from app.presentation.routes.auth import router as auth_router
from app.presentation.routes.health import router as health_router
from app.presentation.routes.tag import router as tag_router

__all__ = ["auth_router", "health_router", "tag_router"]
