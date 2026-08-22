from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from liyan_server.settings import Settings


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessChecks(BaseModel):
    database: Literal["available", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


def database_is_available(database_url: str) -> bool:
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    finally:
        if engine is not None:
            engine.dispose()


def health_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live", operation_id="get_liveness", response_model=LivenessResponse)
    def get_liveness() -> LivenessResponse:
        return LivenessResponse(status="alive")

    @router.get(
        "/ready",
        operation_id="get_readiness",
        response_model=ReadinessResponse,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    )
    def get_readiness() -> ReadinessResponse | JSONResponse:
        if database_is_available(settings.database_url):
            return ReadinessResponse(
                status="ready",
                checks=ReadinessChecks(database="available"),
            )

        body = ReadinessResponse(
            status="not_ready",
            checks=ReadinessChecks(database="unavailable"),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )

    return router
