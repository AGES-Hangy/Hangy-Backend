"""FastAPI route modules."""

from app.presentation.routes.auth import router as auth_router
from app.presentation.routes.health import router as health_router

__all__ = ["auth_router", "health_router"]
