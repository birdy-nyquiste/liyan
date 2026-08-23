from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from liyan_server.database import Database
from liyan_server.object_storage import ObjectStorage, ObjectStorageState


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessChecks(BaseModel):
    database: Literal["available", "unavailable"]
    #: Reported, never gating. Object storage is required for file 来源 only —
    #: pasted and URL sources never touch it — and the Technical Spec is
    #: explicit that a short R2 outage must not become a restart condition.
    object_storage: ObjectStorageState


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


def health_router(database: Database, storage: ObjectStorage) -> APIRouter:
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
        storage_state = storage.state()
        if database.is_available():
            return ReadinessResponse(
                status="ready",
                checks=ReadinessChecks(
                    database="available", object_storage=storage_state
                ),
            )

        body = ReadinessResponse(
            status="not_ready",
            checks=ReadinessChecks(
                database="unavailable", object_storage=storage_state
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )

    return router
