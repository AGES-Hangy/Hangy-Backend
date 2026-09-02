"""FastAPI route modules."""

from app.presentation.routes.auth import router as auth_router
from app.presentation.routes.events import router as events_router
from app.presentation.routes.health import router as health_router
from app.presentation.routes.tags import router as tags_router

__all__ = ["auth_router", "events_router", "health_router", "tags_router"]
