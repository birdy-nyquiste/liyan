from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    Database,
    Execution,
    LiyanArticle,
    PublishTask,
    Source,
    SourceRevision,
    Task,
    TaskVersion,
    TaskVersionSource,
    User,
    aware_utc,
)
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.liyan.runs import LIYAN_TARGET_TYPE
from liyan_server.zhiyan.runs import ZHIYAN_TARGET_TYPE


class TaskSummary(BaseModel):
    id: str
    number: int
    display_name: str
    first_source_title: str
    additional_source_count: int
    created_at: datetime
    current_version_id: str
    current_version_number: int
    can_delete: bool
    delete_disabled_reason: str | None


class TaskListResponse(BaseModel):
    items: list[TaskSummary]


class RenameTaskRequest(BaseModel):
    display_name: str


class DeleteTaskRequest(BaseModel):
    confirmed: Literal[True]


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
    publication_pending = session.scalar(
        select(PublishTask.id).where(
            PublishTask.task_id == task.id,
            PublishTask.status == "pending",
        )
    )
    return TaskSummary(
        id=str(task.id),
        number=task.number,
        display_name=task.display_name,
        first_source_title=revisions[0].title,
        additional_source_count=max(0, len(revisions) - 1),
        created_at=aware_utc(task.created_at),
        current_version_id=str(task.current_version_id),
        current_version_number=version.number,
        can_delete=publication_pending is None,
        delete_disabled_reason=(
            None
            if publication_pending is None
            else "关联的发布任务仍在执行，结束后才能删除立言任务。"
        ),
    )


def task_router(database: Database, current_user: CurrentUserDependency) -> APIRouter:
    router = APIRouter()

    def owned_task(session: Session, task_id: UUID, owner_id: UUID) -> Task:
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.owner_id == owner_id,
                Task.number.is_not(None),
                Task.deleted_at.is_(None),
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
            .where(
                Task.owner_id == user.id,
                Task.number.is_not(None),
                Task.deleted_at.is_(None),
            )
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

    @router.delete(
        "/tasks/{task_id}",
        operation_id="delete_task",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["tasks"],
    )
    def delete_task(
        task_id: UUID,
        _: DeleteTaskRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> None:
        task = session.scalar(
            select(Task)
            .where(
                Task.id == task_id,
                Task.owner_id == user.id,
                Task.number.is_not(None),
                Task.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        pending_publication = session.scalar(
            select(PublishTask.id).where(
                PublishTask.task_id == task.id,
                PublishTask.status == "pending",
            )
        )
        if pending_publication is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="关联的发布任务仍在执行，结束后才能删除立言任务。",
            )

        now = datetime.now(UTC)
        source_revision_ids = list(
            session.scalars(
                select(SourceRevision.id)
                .join(Source, Source.id == SourceRevision.source_id)
                .where(Source.task_id == task.id)
            )
        )
        article_ids = list(
            session.scalars(
                select(LiyanArticle.id)
                .join(TaskVersion, TaskVersion.id == LiyanArticle.task_version_id)
                .where(TaskVersion.task_id == task.id)
            )
        )
        unfinished = list(
            session.scalars(
                select(Execution).where(
                    Execution.status.in_(ACTIVE_EXECUTION_STATUSES),
                    (
                        (Execution.target_type == ZHIYAN_TARGET_TYPE)
                        & Execution.target_id.in_(source_revision_ids)
                    )
                    | (
                        (Execution.target_type == LIYAN_TARGET_TYPE)
                        & Execution.target_id.in_(article_ids)
                    ),
                )
            )
        )
        for execution in unfinished:
            execution.cancellation_requested_at = now
            if execution.status == "queued":
                execution.status = "cancelled"
                execution.error_code = "task_deleted"
                execution.error_message = "所属立言任务已删除。"
                execution.finished_at = now
            else:
                execution.status = "cancel_requested"
        task.deleted_at = now
        session.commit()

    return router
