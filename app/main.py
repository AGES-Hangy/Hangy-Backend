from fastapi import FastAPI

from app.presentation.routes import health_router

app = FastAPI(
    title="Hangy Backend",
    description="API backend do projeto Hangy.",
    version="0.1.0",
)

app.include_router(health_router)
