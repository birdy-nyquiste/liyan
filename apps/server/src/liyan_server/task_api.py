from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    Database,
    SourceRevision,
    Task,
    TaskVersion,
    TaskVersionSource,
    User,
)


class TaskSummary(BaseModel):
    id: str
    number: int
    display_name: str
    first_source_title: str
    additional_source_count: int
    created_at: datetime
    current_version_id: str
    current_version_number: int


class TaskListResponse(BaseModel):
    items: list[TaskSummary]


class RenameTaskRequest(BaseModel):
    display_name: str


def task_summary(session: Session, task: Task) -> TaskSummary:
    if task.current_version_id is None:
        raise ValueError("A formal task must reference a current version.")
    version = session.get(TaskVersion, task.current_version_id)
    if version is None:
        raise ValueError("A formal task must reference an existing current version.")
    revisions = session.scalars(
        select(SourceRevision)
        .join(
            TaskVersionSource,
            TaskVersionSource.source_revision_id == SourceRevision.id,
        )
        .where(TaskVersionSource.task_version_id == task.current_version_id)
        .order_by(TaskVersionSource.position)
    ).all()
    if not revisions:
        raise ValueError("A formal task version must contain at least one source revision.")
    if task.number is None or task.display_name is None or task.created_at is None:
        raise ValueError("A formal task must contain its recognition fields.")
    return TaskSummary(
        id=str(task.id),
        number=task.number,
        display_name=task.display_name,
        first_source_title=revisions[0].title,
        additional_source_count=max(0, len(revisions) - 1),
        created_at=(
            task.created_at
            if task.created_at.tzinfo is not None
            else task.created_at.replace(tzinfo=UTC)
        ),
        current_version_id=str(task.current_version_id),
        current_version_number=version.number,
    )


def task_router(database: Database, current_user: CurrentUserDependency) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/tasks",
        operation_id="list_tasks",
        response_model=TaskListResponse,
        tags=["tasks"],
    )
    def list_tasks(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskListResponse:
        tasks = session.scalars(
            select(Task)
            .where(Task.owner_id == user.id, Task.number.is_not(None))
            .order_by(Task.number.desc())
        ).all()
        return TaskListResponse(items=[task_summary(session, task) for task in tasks])

    @router.patch(
        "/tasks/{task_id}",
        operation_id="rename_task",
        response_model=TaskSummary,
        tags=["tasks"],
    )
    def rename_task(
        task_id: UUID,
        request: RenameTaskRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskSummary:
        display_name = " ".join(request.display_name.split())
        if not display_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A task display name is required.",
            )
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.owner_id == user.id,
                Task.number.is_not(None),
            )
        )
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        task.display_name = display_name
        session.commit()
        return task_summary(session, task)

    return router
