from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from liyan_server.billing.packs import BillingState, billing_state
from liyan_server.database import Database
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.object_storage import ObjectStorage, ObjectStorageState
from liyan_server.settings import Settings
from liyan_server.worker_health import WorkerState, worker_state


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessChecks(BaseModel):
    database: Literal["available", "unavailable"]
    #: Gating, unlike object storage: everything this server does for a user is
    #: queued work, so an unreachable broker means it cannot do its job at all.
    queue: Literal["available", "unavailable"]
    #: Reported, never gating. A silent worker is a real problem, but restarting
    #: the API does not fix it and taking the API out of rotation hides it.
    worker: WorkerState
    #: Reported, never gating. Object storage is required for file 来源 only —
    #: pasted and URL sources never touch it — and the Technical Spec is
    #: explicit that a short R2 outage must not become a restart condition.
    object_storage: ObjectStorageState
    #: Reported, never gating. Without it a user cannot buy 额度; everything they
    #: already hold still spends, so this is a feature that is missing rather
    #: than a server that is broken.
    billing: BillingState


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


def health_router(
    settings: Settings,
    database: Database,
    storage: ObjectStorage,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
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
        checks = ReadinessChecks(
            database="available" if database.is_available() else "unavailable",
            queue="available" if dispatcher.is_reachable() else "unavailable",
            worker=worker_state(database),
            object_storage=storage.state(),
            billing=billing_state(settings),
        )
        # Only the two the server cannot work without decide the verdict. The
        # other two are reported so an operator can see them without a restart
        # being the answer to either.
        healthy = checks.database == "available" and checks.queue == "available"
        if healthy:
            return ReadinessResponse(status="ready", checks=checks)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ReadinessResponse(status="not_ready", checks=checks).model_dump(),
        )

    return router
