from datetime import datetime
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
    aware_utc,
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


class SourceRevisionSummary(BaseModel):
    id: str
    title: str
    provenance: str | None


class TaskVersionDetail(BaseModel):
    id: str
    number: int
    created_at: datetime
    source_revisions: list[SourceRevisionSummary]


def version_source_revisions(session: Session, task_version_id: UUID) -> list[SourceRevision]:
    return list(
        session.scalars(
            select(SourceRevision)
            .join(
                TaskVersionSource,
                TaskVersionSource.source_revision_id == SourceRevision.id,
            )
            .where(TaskVersionSource.task_version_id == task_version_id)
            .order_by(TaskVersionSource.position)
        ).all()
    )


def task_summary(session: Session, task: Task) -> TaskSummary:
    if task.current_version_id is None:
        raise ValueError("A formal task must reference a current version.")
    version = session.get(TaskVersion, task.current_version_id)
    if version is None:
        raise ValueError("A formal task must reference an existing current version.")
    revisions = version_source_revisions(session, task.current_version_id)
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
        created_at=aware_utc(task.created_at),
        current_version_id=str(task.current_version_id),
        current_version_number=version.number,
    )


def task_router(database: Database, current_user: CurrentUserDependency) -> APIRouter:
    router = APIRouter()

    def owned_task(session: Session, task_id: UUID, owner_id: UUID) -> Task:
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.owner_id == owner_id,
                Task.number.is_not(None),
            )
        )
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return task

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
        task = owned_task(session, task_id, user.id)
        task.display_name = display_name
        session.commit()
        return task_summary(session, task)

    @router.get(
        "/tasks/{task_id}/current-version",
        operation_id="get_current_task_version",
        response_model=TaskVersionDetail,
        tags=["tasks"],
    )
    def get_current_task_version(
        task_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskVersionDetail:
        task = owned_task(session, task_id, user.id)
        version = (
            session.get(TaskVersion, task.current_version_id)
            if task.current_version_id
            else None
        )
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task version not found.",
            )
        return TaskVersionDetail(
            id=str(version.id),
            number=version.number,
            created_at=aware_utc(version.created_at),
            source_revisions=[
                SourceRevisionSummary(
                    id=str(revision.id),
                    title=revision.title,
                    provenance=revision.provenance,
                )
                for revision in version_source_revisions(session, version.id)
            ],
        )

    return router
