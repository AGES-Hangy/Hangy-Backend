"""FastAPI route modules."""

from app.presentation.routes.health import router as health_router

__all__ = ["health_router"]
