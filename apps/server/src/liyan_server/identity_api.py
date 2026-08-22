from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import User


class CurrentUserResponse(BaseModel):
    id: str
    email: str


def identity_router(current_user: CurrentUserDependency) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/auth/me",
        operation_id="get_current_user",
        response_model=CurrentUserResponse,
        tags=["identity"],
    )
    def get_current_user(
        user: Annotated[User, Depends(current_user)],
    ) -> CurrentUserResponse:
        return CurrentUserResponse(id=str(user.id), email=user.email)

    return router
