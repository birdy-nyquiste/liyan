"""发布任务: choosing an eligible Revision, a target, and confirming once.

Confirmation is the only moment the article is read. Everything the platform
will receive is copied into an immutable 发布任务 before anything is dispatched,
so no later save, restore, or source edit can change what was submitted.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    Database,
    Execution,
    LiyanArticle,
    LiyanRevision,
    PublishTask,
    Task,
    TaskVersion,
    User,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import PublishTaskStatus
from liyan_server.liyan.revisions import UNSAVED_EDITS, load_history
from liyan_server.publication.blog import POST_TYPE, PREVIEW_STATUS
from liyan_server.publication.orchestration import dispatch_publication
from liyan_server.publication.runs import new_publish_execution
from liyan_server.publication.targets import PublicationTarget, target_for, targets_for
from liyan_server.settings import Settings
from liyan_server.task_creation.contracts import ExecutionResponse, execution_response

SUPERSEDED_REVISION = "该 Revision 已不是当前任务版本中最新的已保存 Revision。"
TARGET_NOT_FOUND = "Publication target not found."
PUBLISH_TASK_NOT_FOUND = "Publication task not found."
IDEMPOTENCY_MISMATCH = "相同幂等键不能用于不同的发布请求。"


class PublicationTargetResponse(BaseModel):
    key: str
    platform: str
    display_name: str
    site_url: str
    author: str

    @classmethod
    def of(cls, target: PublicationTarget, author: str) -> "PublicationTargetResponse":
        """One target as it looks to one user, under their own author name."""
        return cls(
            key=target.key,
            platform=target.platform,
            display_name=target.display_name,
            site_url=target.site_url,
            author=author,
        )


class PublicationTargetListResponse(BaseModel):
    items: list[PublicationTargetResponse]


class EligibleArticleResponse(BaseModel):
    task_id: str
    task_number: int
    task_display_name: str
    task_version_id: str
    revision_id: str
    revision_number: int
    title: str
    body_markdown: str
    content_hash: str
    saved_at: datetime


class EligibleArticleListResponse(BaseModel):
    items: list[EligibleArticleResponse]


class ConfirmPublicationRequest(BaseModel):
    idempotency_key: str
    task_id: UUID
    revision_id: UUID
    target_key: str
    #: The browser's draft hash. Present means "this is what I am looking at";
    #: a mismatch is unsaved editing and must not reach Blog.
    working_copy_hash: str | None = None


class PublishTaskResponse(BaseModel):
    id: str
    status: PublishTaskStatus
    task_id: str
    task_version_id: str
    revision_id: str
    revision_number: int
    title: str
    body_markdown: str
    target: PublicationTargetResponse
    post_type: str
    requested_status: str
    preview_url: str | None
    external_slug: str | None
    external_version: str | None
    response_evidence: dict[str, object] | None
    failure_message: str | None
    created_at: datetime
    completed_at: datetime | None
    execution: ExecutionResponse | None

    @classmethod
    def of(
        cls, publish_task: PublishTask, execution: Execution | None
    ) -> "PublishTaskResponse":
        return cls(
            id=str(publish_task.id),
            status=publish_task.status,
            task_id=str(publish_task.task_id),
            task_version_id=str(publish_task.task_version_id),
            revision_id=str(publish_task.revision_id),
            revision_number=publish_task.revision_number,
            title=publish_task.title,
            body_markdown=publish_task.body_markdown,
            target=PublicationTargetResponse(
                key=publish_task.target_key,
                platform=publish_task.target_platform,
                display_name=publish_task.target_display_name,
                site_url=publish_task.target_site_url,
                author=publish_task.target_author,
            ),
            post_type=publish_task.post_type,
            requested_status=publish_task.requested_status,
            preview_url=publish_task.preview_url,
            external_slug=publish_task.external_slug,
            external_version=publish_task.external_version,
            response_evidence=publish_task.response_evidence,
            failure_message=publish_task.failure_message,
            created_at=aware_utc(publish_task.created_at),
            completed_at=(
                aware_utc(publish_task.completed_at)
                if publish_task.completed_at is not None
                else None
            ),
            execution=execution_response(execution) if execution is not None else None,
        )


def publication_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter(prefix="/publication", tags=["publication"])

    def latest_execution(session: Session, publish_task: PublishTask) -> Execution | None:
        return session.scalar(
            select(Execution)
            .where(Execution.target_id == publish_task.id)
            .order_by(Execution.attempt.desc())
            .limit(1)
        )

    def owned_publish_task(
        session: Session, publish_task_id: UUID, owner_id: UUID
    ) -> PublishTask:
        publish_task = session.scalar(
            select(PublishTask).where(
                PublishTask.id == publish_task_id, PublishTask.owner_id == owner_id
            )
        )
        if publish_task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=PUBLISH_TASK_NOT_FOUND
            )
        return publish_task

    def newest_saved(session: Session, version_id: UUID) -> LiyanRevision | None:
        article = session.scalar(
            select(LiyanArticle).where(LiyanArticle.task_version_id == version_id)
        )
        if article is None:
            return None
        return load_history(session, article.id).current

    @router.get(
        "/targets",
        operation_id="list_publication_targets",
        response_model=PublicationTargetListResponse,
    )
    def list_publication_targets(
        user: Annotated[User, Depends(current_user)],
    ) -> PublicationTargetListResponse:
        return PublicationTargetListResponse(
            items=[
                PublicationTargetResponse.of(target, author)
                for target in targets_for(settings, user.email)
                if (author := target.author_for(user.email)) is not None
            ]
        )

    @router.get(
        "/eligible-articles",
        operation_id="list_eligible_articles",
        response_model=EligibleArticleListResponse,
    )
    def list_eligible_articles(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> EligibleArticleListResponse:
        tasks = session.scalars(
            select(Task)
            .where(Task.owner_id == user.id, Task.number.is_not(None))
            .order_by(Task.number.desc())
        ).all()
        items: list[EligibleArticleResponse] = []
        for task in tasks:
            number = task.number
            if task.current_version_id is None or number is None:
                continue
            revision = newest_saved(session, task.current_version_id)
            if revision is None:
                continue
            items.append(
                EligibleArticleResponse(
                    task_id=str(task.id),
                    task_number=number,
                    task_display_name=task.display_name or f"任务 {number}",
                    task_version_id=str(task.current_version_id),
                    revision_id=str(revision.id),
                    revision_number=revision.number,
                    title=revision.title,
                    body_markdown=revision.body_markdown,
                    content_hash=revision.content_hash,
                    saved_at=aware_utc(revision.created_at),
                )
            )
        return EligibleArticleListResponse(items=items)

    @router.post(
        "/publish-tasks",
        operation_id="confirm_publication",
        response_model=PublishTaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def confirm_publication(
        request: ConfirmPublicationRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> PublishTaskResponse:
        replay = session.scalar(
            select(PublishTask).where(
                PublishTask.owner_id == user.id,
                PublishTask.idempotency_key == request.idempotency_key,
            )
        )
        if replay is not None:
            if (
                replay.revision_id != request.revision_id
                or replay.target_key != request.target_key
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=IDEMPOTENCY_MISMATCH
                )
            return PublishTaskResponse.of(replay, latest_execution(session, replay))
        target = target_for(settings, user.email, request.target_key)
        author = target.author_for(user.email) if target is not None else None
        if target is None or author is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=TARGET_NOT_FOUND
            )
        task, version = _owned_current(session, request.task_id, user.id)
        revision = newest_saved(session, version.id)
        if revision is None or revision.id != request.revision_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=SUPERSEDED_REVISION
            )
        if (
            request.working_copy_hash is not None
            and request.working_copy_hash != revision.content_hash
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=UNSAVED_EDITS)
        now = datetime.now(UTC)
        publish_task = PublishTask(
            owner_id=user.id,
            task_id=task.id,
            task_version_id=version.id,
            revision_id=revision.id,
            revision_number=revision.number,
            target_key=target.key,
            target_platform=target.platform,
            target_display_name=target.display_name,
            target_site_url=target.site_url,
            target_api_base_url=target.api_base_url,
            target_author=author,
            post_type=POST_TYPE,
            requested_status=PREVIEW_STATUS,
            title=revision.title,
            body_markdown=revision.body_markdown,
            content_hash=revision.content_hash,
            status="pending",
            idempotency_key=request.idempotency_key,
            created_at=now,
        )
        session.add(publish_task)
        session.flush()
        execution = new_publish_execution(publish_task, created_at=now)
        session.add(execution)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            replay = session.scalar(
                select(PublishTask).where(
                    PublishTask.owner_id == user.id,
                    PublishTask.idempotency_key == request.idempotency_key,
                )
            )
            if replay is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=IDEMPOTENCY_MISMATCH
                ) from error
            return PublishTaskResponse.of(replay, latest_execution(session, replay))
        dispatch_publication(database, dispatcher, execution.id, publish_task.id)
        session.expire_all()
        return PublishTaskResponse.of(
            session.get(PublishTask, publish_task.id) or publish_task,
            session.get(Execution, execution.id),
        )

    @router.get(
        "/publish-tasks/{publish_task_id}",
        operation_id="get_publish_task",
        response_model=PublishTaskResponse,
    )
    def get_publish_task(
        publish_task_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> PublishTaskResponse:
        publish_task = owned_publish_task(session, publish_task_id, user.id)
        return PublishTaskResponse.of(publish_task, latest_execution(session, publish_task))

    return router


def _owned_current(session: Session, task_id: UUID, owner_id: UUID) -> tuple[Task, TaskVersion]:
    task = session.scalar(
        select(Task).where(
            Task.id == task_id, Task.owner_id == owner_id, Task.number.is_not(None)
        )
    )
    version = (
        session.get(TaskVersion, task.current_version_id)
        if task is not None and task.current_version_id is not None
        else None
    )
    if task is None or version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task, version
