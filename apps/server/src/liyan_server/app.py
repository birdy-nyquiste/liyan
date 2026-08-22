from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from liyan_server.health import health_router
from liyan_server.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    current_settings = settings or Settings()
    application = FastAPI(
        title="立言阁 Server API",
        version="0.1.0",
        description="The server-owned API contract for 立言阁.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(current_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router(current_settings))
    return application


app = create_app()
