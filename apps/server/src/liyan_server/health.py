from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from liyan_server.database import Database


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessChecks(BaseModel):
    database: Literal["available", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


def health_router(database: Database) -> APIRouter:
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
        if database.is_available():
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
