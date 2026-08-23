"""发布任务: choosing an eligible Revision, a target, and confirming once.

Confirmation is the only moment the article is read. Everything the platform
will receive is copied into an immutable 发布任务 before anything is dispatched,
so no later save, restore, or source edit can change what was submitted.

"Once" is literal. One Revision reaches one 发布目标 through exactly one 发布任务,
so a second Preview for that pair cannot be created by any route. What follows
from that:

- A definitive failure is resent through `retry`, which sends the snapshot the
  first attempt sent. There is no other way back to a submitted pair, so a
  retry cannot become a way to publish something newer.
- 结果未知 and success are terminal. Blog v0.11 has no idempotency key and no
  Preview lookup, so neither can be resolved from here (ADR-0001).
- A newer Revision may reach the same target, because that is a second article
  and Blog has no update. It is a second Blog item, so the user is told before
  it is created rather than after.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
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
from liyan_server.publication.blog import POST_TYPE, PREVIEW_STATUS, UNKNOWN_OUTCOME_MESSAGE
from liyan_server.publication.orchestration import dispatch_publication
from liyan_server.publication.runs import PUBLISH_TARGET_TYPE, new_publish_execution
from liyan_server.publication.targets import PublicationTarget, target_for, targets_for
from liyan_server.settings import Settings
from liyan_server.task_creation.contracts import ExecutionResponse, execution_response

SUPERSEDED_REVISION = "该 Revision 已不是当前任务版本中最新的已保存 Revision。"
TARGET_NOT_FOUND = "Publication target not found."
PUBLISH_TASK_NOT_FOUND = "Publication task not found."
IDEMPOTENCY_MISMATCH = "相同幂等键不能用于不同的发布请求。"
EMPTY_AUTHOR = "请填写发布到 Blog 的作者名。"
ALREADY_SUBMITTED = "该 Revision 已提交到该发布目标，不能重复创建 Preview。"
RETRY_INSTEAD = "该 Revision 上次提交到该发布目标失败，请重试原提交，不要新建发布任务。"
RETRY_IN_PROGRESS = "本次提交仍在进行中，请等待结果。"
ALREADY_PREVIEWED = "本次提交已创建 Blog Preview，不能重试。"
EXISTING_PREVIEW_WARNING = (
    "该立言任务已有文章提交到这个发布目标。Blog 不会替换原有内容，"
    "继续发布会新建另一条 Blog 内容。确认后可以继续。"
)

#: Both publishing routes refuse the same two ways, and the browser tells them
#: apart by status alone. Declared so the generated contract says so too: a
#: client that treats 412 as a plain error strands the user at the warning.
PUBLISH_REFUSALS: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {
        "description": "Refused outright: nothing about this request can be made to work as sent."
    },
    status.HTTP_412_PRECONDITION_FAILED: {
        "description": (
            "The target may already hold an item for this 立言任务. Resend with "
            "`acknowledge_existing_preview` once the user has read the warning."
        )
    },
}

#: Statuses under which Blog may hold an item for this 立言任务. 结果未知 counts:
#: the submission may well have created one, and nothing here can check.
_MAY_EXIST_ON_BLOG: frozenset[PublishTaskStatus] = frozenset({"succeeded", "outcome_unknown"})


class PublicationTargetResponse(BaseModel):
    key: str
    platform: str
    display_name: str
    site_url: str

    @classmethod
    def of(cls, target: PublicationTarget) -> "PublicationTargetResponse":
        return cls(
            key=target.key,
            platform=target.platform,
            display_name=target.display_name,
            site_url=target.site_url,
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


class PublishTaskListResponse(BaseModel):
    items: list["PublishTaskResponse"]


class ConfirmPublicationRequest(BaseModel):
    idempotency_key: str
    task_id: UUID
    revision_id: UUID
    target_key: str
    #: The name Blog will display. Blog requires it and treats one name as one
    #: author across submissions, so it is trimmed and never blank.
    author: str = Field(min_length=1, max_length=100)
    #: The browser's draft hash. Present means "this is what I am looking at";
    #: a mismatch is unsaved editing and must not reach Blog.
    working_copy_hash: str | None = None
    #: Set once the user has been told this target may already hold an item for
    #: this 立言任务 and still wants a second one. Defaults to refusing, so a
    #: client that never asks can never create the second item by accident.
    acknowledge_existing_preview: bool = False

    @field_validator("author")
    @classmethod
    def trim_author(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError(EMPTY_AUTHOR)
        return trimmed


class RetryPublicationRequest(BaseModel):
    """Identity and consent — never content.

    The 发布任务 already holds everything the attempt will send. A body that could
    name a title, an author, or a Revision would be a way to publish something
    newer under the word "retry".
    """

    idempotency_key: str
    #: Same meaning as at confirmation. A retry can outlive the reason it was
    #: safe: a newer Revision may have reached this target while it sat failed.
    acknowledge_existing_preview: bool = False


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
    author: str
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
    attempts: list[ExecutionResponse]

    @classmethod
    def of(cls, publish_task: PublishTask, executions: list[Execution]) -> "PublishTaskResponse":
        execution = executions[-1] if executions else None
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
            ),
            author=publish_task.author,
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
            attempts=[execution_response(attempt) for attempt in executions],
        )


def publication_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter(prefix="/publication", tags=["publication"])

    def publish_executions(session: Session, publish_task: PublishTask) -> list[Execution]:
        return list(
            session.scalars(
                select(Execution)
                .where(
                    Execution.target_type == PUBLISH_TARGET_TYPE,
                    Execution.target_id == publish_task.id,
                )
                .order_by(Execution.attempt)
            ).all()
        )

    def owned_publish_task(session: Session, publish_task_id: UUID, owner_id: UUID) -> PublishTask:
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
                PublicationTargetResponse.of(target) for target in targets_for(settings, user.email)
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
            .where(
                Task.owner_id == user.id,
                Task.number.is_not(None),
                Task.deleted_at.is_(None),
            )
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
        responses=PUBLISH_REFUSALS,
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
                or replay.author != request.author
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=IDEMPOTENCY_MISMATCH
                )
            return PublishTaskResponse.of(replay, publish_executions(session, replay))
        target = target_for(settings, user.email, request.target_key)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TARGET_NOT_FOUND)
        task, version = _owned_current(session, request.task_id, user.id)
        revision = newest_saved(session, version.id)
        if revision is None or revision.id != request.revision_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SUPERSEDED_REVISION)
        if (
            request.working_copy_hash is not None
            and request.working_copy_hash != revision.content_hash
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=UNSAVED_EDITS)
        existing = _submitted_pair(session, revision.id, target.key)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=_second_submission_refusal(existing)
            )
        if not request.acknowledge_existing_preview and _reached_target(
            session, task.id, target.key
        ):
            # 412 rather than 409: nothing conflicts, a precondition the
            # user alone can satisfy is simply unmet. It also lets the browser
            # tell this one answer apart from every other refusal without
            # matching on the message.
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail=EXISTING_PREVIEW_WARNING,
            )
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
            author=request.author,
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
            if replay is not None:
                return PublishTaskResponse.of(replay, publish_executions(session, replay))
            # Two confirmations of the same pair can both pass the check above
            # and only one can insert. The loser is a duplicate, not a mistyped
            # idempotency key, and must be told the same thing either way.
            raced = _submitted_pair(session, request.revision_id, request.target_key)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    IDEMPOTENCY_MISMATCH if raced is None else _second_submission_refusal(raced)
                ),
            ) from error
        dispatch_publication(database, dispatcher, execution.id, publish_task.id)
        session.expire_all()
        return PublishTaskResponse.of(
            session.get(PublishTask, publish_task.id) or publish_task,
            publish_executions(session, publish_task),
        )

    @router.post(
        "/publish-tasks/{publish_task_id}/retry",
        operation_id="retry_publication",
        response_model=PublishTaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses=PUBLISH_REFUSALS,
    )
    def retry_publication(
        publish_task_id: UUID,
        request: RetryPublicationRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> PublishTaskResponse:
        """Send the snapshot again, and only the snapshot.

        Retrying reads nothing the user could have changed since: the 发布任务
        already holds the title, body, author, and target this attempt will use.
        A newer article therefore cannot ride out on a retry — publishing it is
        a new confirmation, with the warning that goes with one.
        """
        publish_task = session.scalar(
            select(PublishTask)
            .where(PublishTask.id == publish_task_id, PublishTask.owner_id == user.id)
            .with_for_update()
        )
        if publish_task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=PUBLISH_TASK_NOT_FOUND
            )
        if publish_task.status != "failed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_retry_refusal(publish_task.status),
            )
        # Time passed while this sat failed, and a newer Revision may have
        # reached the target meanwhile. Resending now creates the second Blog
        # item the confirmation warning exists to prevent, so it asks again.
        if not request.acknowledge_existing_preview and _reached_target(
            session, publish_task.task_id, publish_task.target_key
        ):
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail=EXISTING_PREVIEW_WARNING,
            )
        attempts = publish_executions(session, publish_task)
        now = datetime.now(UTC)
        execution = new_publish_execution(
            publish_task,
            created_at=now,
            attempt=attempts[-1].attempt + 1 if attempts else 1,
            origin="manual",
            idempotency_key=request.idempotency_key,
        )
        publish_task.status = "pending"
        publish_task.failure_code = None
        publish_task.failure_message = None
        publish_task.completed_at = None
        session.add(execution)
        try:
            session.commit()
        except IntegrityError as error:
            # A repeated retry key, or a concurrent retry that won the
            # one-active-Execution index. This attempt started nothing, so it
            # must not answer as though it had — the other one is in progress.
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=RETRY_IN_PROGRESS
            ) from error
        dispatch_publication(database, dispatcher, execution.id, publish_task.id)
        session.expire_all()
        return PublishTaskResponse.of(
            session.get(PublishTask, publish_task_id) or publish_task,
            publish_executions(session, publish_task),
        )

    @router.get(
        "/publish-tasks",
        operation_id="list_publish_tasks",
        response_model=PublishTaskListResponse,
    )
    def list_publish_tasks(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> PublishTaskListResponse:
        publish_tasks = session.scalars(
            select(PublishTask)
            .where(PublishTask.owner_id == user.id)
            .order_by(PublishTask.created_at.desc())
        ).all()
        return PublishTaskListResponse(
            items=[
                PublishTaskResponse.of(publish_task, publish_executions(session, publish_task))
                for publish_task in publish_tasks
            ]
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
        return PublishTaskResponse.of(publish_task, publish_executions(session, publish_task))

    return router


def _submitted_pair(
    session: Session, revision_id: UUID, target_key: str
) -> PublishTask | None:
    """The 发布任务 already holding this Revision and target, if one exists.

    One pair is allowed one 发布任务, forever. That is what stops a second Blog
    item, and it is also what makes a retry unambiguous: there is exactly one
    snapshot it could resend.
    """
    return session.scalar(
        select(PublishTask).where(
            PublishTask.revision_id == revision_id, PublishTask.target_key == target_key
        )
    )


def _reached_target(session: Session, task_id: UUID, target_key: str) -> bool:
    """Whether this 立言任务 may already have an item on this 发布目标.

    A second Revision of the same article on the same destination is a second
    Blog item, not a replacement — v0.11 has no update. That is a legitimate
    thing to want and a bad thing to do unknowingly, so it is warned about
    rather than refused.
    """
    return (
        session.scalar(
            select(PublishTask.id).where(
                PublishTask.task_id == task_id,
                PublishTask.target_key == target_key,
                PublishTask.status.in_(_MAY_EXIST_ON_BLOG),
            )
        )
        is not None
    )


def _retry_refusal(current: PublishTaskStatus) -> str:
    """Why this 发布任务 may not be retried; only a definitive failure may.

    结果未知 is the one that matters: Blog may hold an item nobody here can see,
    so ADR-0001 makes it terminal. The user reads the same sentence the outcome
    itself carried, rather than a second wording of the same refusal.
    """
    if current == "succeeded":
        return ALREADY_PREVIEWED
    if current == "outcome_unknown":
        return UNKNOWN_OUTCOME_MESSAGE
    return RETRY_IN_PROGRESS


def _second_submission_refusal(existing: PublishTask) -> str:
    """Why a repeat of one pair is refused, in the terms the user can act on.

    A definitive failure is the one case with a way forward, so it names the
    retry rather than leaving the user to guess that publishing is over.
    """
    return RETRY_INSTEAD if existing.status == "failed" else ALREADY_SUBMITTED


def _owned_current(session: Session, task_id: UUID, owner_id: UUID) -> tuple[Task, TaskVersion]:
    task = session.scalar(
        select(Task)
        .where(
            Task.id == task_id,
            Task.owner_id == owner_id,
            Task.number.is_not(None),
            Task.deleted_at.is_(None),
        )
        .with_for_update()
    )
    version = (
        session.get(TaskVersion, task.current_version_id)
        if task is not None and task.current_version_id is not None
        else None
    )
    if task is None or version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task, version
