from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.presentation.routes import (
    auth_router,
    events_router,
    health_router,
    tags_router,
)

app = FastAPI(
    title="Hangy Backend",
    description="API backend do projeto Hangy.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(events_router)
app.include_router(tags_router)
