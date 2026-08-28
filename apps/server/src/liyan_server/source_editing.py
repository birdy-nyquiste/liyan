"""来源编辑会话, immutable 任务版本 history, and restoration."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.credit_limits import hold_zhiyan_batch
from liyan_server.database import (
    Database,
    Execution,
    LiyanArticle,
    Source,
    SourceEditSession,
    SourcePreparation,
    SourceRevision,
    Task,
    TaskVersion,
    TaskVersionSource,
    User,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.hashing import canonical_hash as _hash
from liyan_server.liyan.runs import LIYAN_OPERATION
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content
from liyan_server.task_activity import record_task_activity
from liyan_server.task_api import version_source_revisions
from liyan_server.task_creation.confirmation import SourceInput
from liyan_server.zhiyan.orchestration import queue_initial_runs
from liyan_server.zhiyan.runs import ZHIYAN_OPERATION

HISTORICAL_READ_ONLY = "历史任务版本只读，恢复为当前版本后才能继续操作。"
ACTIVE_RUN_BLOCK = "知言或立言正在生成，暂时不能编辑来源或恢复历史版本。"


class VersionSource(BaseModel):
    source_id: str
    id: str
    title: str
    body: str
    provenance: str | None


class VersionCapabilities(BaseModel):
    can_edit: bool
    can_restore: bool
    unavailable_reason: str | None


class TaskVersionSnapshot(BaseModel):
    id: str
    number: int
    created_at: datetime
    is_current: bool
    sources: list[VersionSource]
    capabilities: VersionCapabilities


class TaskVersionHistory(BaseModel):
    items: list[TaskVersionSnapshot]
    historical_limit: int = 3


class SourceEditSessionResponse(BaseModel):
    id: str
    base_version: TaskVersionSnapshot


class SaveSourceItem(BaseModel):
    source_id: UUID | None = None
    base_revision_id: UUID | None = None
    prepared_source_id: UUID | None = None
    content: SourceInput | None = None


class SaveSourceEditRequest(BaseModel):
    idempotency_key: str
    sources: list[SaveSourceItem] = Field(min_length=1, max_length=3)
    accepted_warning_versions: dict[UUID, int] = Field(default_factory=dict)


class RestoreVersionRequest(BaseModel):
    idempotency_key: str


def _owned_task(
    session: Session, task_id: UUID, owner_id: UUID, *, for_update: bool = False
) -> Task:
    statement = select(Task).where(
        Task.id == task_id,
        Task.owner_id == owner_id,
        Task.number.is_not(None),
        Task.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    task = session.scalar(statement)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


def _has_active_runs(session: Session, version_id: UUID) -> bool:
    revision_ids = select(TaskVersionSource.source_revision_id).where(
        TaskVersionSource.task_version_id == version_id
    )
    article_ids = select(LiyanArticle.id).where(LiyanArticle.task_version_id == version_id)
    return (
        session.scalar(
            select(func.count())
            .select_from(Execution)
            .where(
                or_(
                    and_(
                        Execution.operation == ZHIYAN_OPERATION,
                        Execution.target_id.in_(revision_ids),
                    ),
                    and_(
                        Execution.operation == LIYAN_OPERATION,
                        Execution.target_id.in_(article_ids),
                    ),
                ),
                Execution.status.in_(ACTIVE_EXECUTION_STATUSES),
            )
        )
        or 0
    ) > 0


def _snapshot(
    session: Session,
    task: Task,
    version: TaskVersion,
    *,
    active_runs: bool | None = None,
) -> TaskVersionSnapshot:
    current = task.current_version_id == version.id
    blocked = (
        _has_active_runs(session, task.current_version_id)
        if active_runs is None and task.current_version_id is not None
        else bool(active_runs)
    )
    reason = ACTIVE_RUN_BLOCK if blocked else (None if current else HISTORICAL_READ_ONLY)
    revisions = version_source_revisions(session, version.id)
    source_ids = {revision.id: revision.source_id for revision in revisions}
    return TaskVersionSnapshot(
        id=str(version.id),
        number=version.number,
        created_at=aware_utc(version.created_at),
        is_current=current,
        sources=[
            VersionSource(
                source_id=str(source_ids[revision.id]),
                id=str(revision.id),
                title=revision.title,
                body=revision.body,
                provenance=revision.provenance,
            )
            for revision in revisions
        ],
        capabilities=VersionCapabilities(
            can_edit=current and not blocked,
            can_restore=not current and not blocked,
            unavailable_reason=reason,
        ),
    )


def _changed_revision_ids(
    session: Session, base_version_id: UUID, saved_version_id: UUID
) -> list[UUID]:
    base_ids = {revision.id for revision in version_source_revisions(session, base_version_id)}
    return [
        revision.id
        for revision in version_source_revisions(session, saved_version_id)
        if revision.id not in base_ids
    ]


def source_editing_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter()

    def owned_edit(session: Session, edit_id: UUID, owner_id: UUID) -> SourceEditSession:
        edit = session.scalar(
            select(SourceEditSession)
            .join(Task, Task.id == SourceEditSession.task_id)
            .where(
                SourceEditSession.id == edit_id,
                SourceEditSession.owner_id == owner_id,
                Task.deleted_at.is_(None),
            )
        )
        if edit is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Source edit session not found."
            )
        return edit

    @router.get(
        "/tasks/{task_id}/versions",
        response_model=TaskVersionHistory,
        operation_id="list_task_versions",
        tags=["source editing"],
    )
    def list_versions(
        task_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskVersionHistory:
        task = _owned_task(session, task_id, user.id)
        versions = list(
            session.scalars(
                select(TaskVersion)
                .where(TaskVersion.task_id == task.id)
                .order_by(TaskVersion.number.desc())
            ).all()
        )
        current = next(version for version in versions if version.id == task.current_version_id)
        visible = [current, *[version for version in versions if version.id != current.id][:3]]
        active = _has_active_runs(session, current.id)
        return TaskVersionHistory(
            items=[_snapshot(session, task, version, active_runs=active) for version in visible]
        )

    @router.post(
        "/tasks/{task_id}/source-edit-sessions",
        response_model=SourceEditSessionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="create_source_edit_session",
        tags=["source editing"],
    )
    def create_edit_session(
        task_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> SourceEditSessionResponse:
        task = _owned_task(session, task_id, user.id)
        if task.current_version_id is None or _has_active_runs(session, task.current_version_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_RUN_BLOCK)
        now = datetime.now(UTC)
        edit = SourceEditSession(
            owner_id=user.id,
            task_id=task.id,
            base_version_id=task.current_version_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(edit)
        session.commit()
        version = session.get(TaskVersion, edit.base_version_id)
        assert version is not None
        return SourceEditSessionResponse(
            id=str(edit.id), base_version=_snapshot(session, task, version, active_runs=False)
        )

    @router.post(
        "/source-edit-sessions/{edit_id}/discard",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="discard_source_edit_session",
        tags=["source editing"],
    )
    def discard_edit_session(
        edit_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> Response:
        edit = owned_edit(session, edit_id, user.id)
        if edit.status == "active":
            edit.status = "discarded"
            edit.updated_at = datetime.now(UTC)
            session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/source-edit-sessions/{edit_id}/save",
        response_model=TaskVersionSnapshot,
        operation_id="save_source_edit_session",
        tags=["source editing"],
    )
    def save_edit_session(
        edit_id: UUID,
        request: SaveSourceEditRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskVersionSnapshot:
        edit = owned_edit(session, edit_id, user.id)
        request_hash = _hash(request.model_dump(mode="json"))
        if edit.status == "saved":
            if (
                edit.save_idempotency_key != request.idempotency_key.strip()
                or edit.save_request_hash != request_hash
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This source edit session was already saved differently.",
                )
            task = _owned_task(session, edit.task_id, user.id)
            version = session.get(TaskVersion, edit.saved_version_id)
            assert version is not None
            changed_ids = _changed_revision_ids(
                session, edit.base_version_id, version.id
            )
            session.commit()
            queue_initial_runs(
                database,
                dispatcher,
                source_revision_ids=changed_ids,
                owner_id=user.id,
                model=settings.zhiyan_model,
            )
            return _snapshot(session, task, version)
        if edit.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This source edit session is no longer active.",
            )
        key = request.idempotency_key.strip()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="An idempotency key is required.",
            )
        task = _owned_task(session, edit.task_id, user.id, for_update=True)
        if task.current_version_id != edit.base_version_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The current task version changed; preserve local edits and start again.",
            )
        if _has_active_runs(session, edit.base_version_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_RUN_BLOCK)
        base_revisions = version_source_revisions(session, edit.base_version_id)
        by_source = {revision.source_id: revision for revision in base_revisions}
        seen_sources: set[UUID] = set()
        seen_prepared: set[UUID] = set()
        resolved: list[
            tuple[Source, SourceRevision | None, SourceInput | None, SourcePreparation | None]
        ] = []
        for item in request.sources:
            if item.source_id is None:
                if item.base_revision_id is not None:
                    raise HTTPException(
                        status_code=422, detail="An added source must use prepared input."
                    )
                source = Source(task_id=task.id)
                base = None
            else:
                if item.source_id in seen_sources:
                    raise HTTPException(status_code=422, detail="A source may appear only once.")
                seen_sources.add(item.source_id)
                base = by_source.get(item.source_id)
                if base is None or base.id != item.base_revision_id:
                    raise HTTPException(
                        status_code=409, detail="A source edit has a stale base Revision."
                    )
                stored_source = session.get(Source, item.source_id)
                assert stored_source is not None
                source = stored_source
            prepared = None
            if item.prepared_source_id is not None:
                if item.prepared_source_id in seen_prepared:
                    raise HTTPException(
                        status_code=422, detail="Prepared input may be used only once."
                    )
                seen_prepared.add(item.prepared_source_id)
                prepared = session.scalar(
                    select(SourcePreparation).where(
                        SourcePreparation.id == item.prepared_source_id,
                        SourcePreparation.owner_id == user.id,
                        SourcePreparation.client_session_id == str(edit.id),
                        SourcePreparation.confirmed_task_id.is_(None),
                    )
                )
                if prepared is None or prepared.status not in {"ready", "warning"}:
                    raise HTTPException(status_code=409, detail="Every new input must be ready.")
                if (
                    prepared.warnings
                    and request.accepted_warning_versions.get(prepared.id) != prepared.input_version
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Accept every source warning before saving.",
                    )
            elif base is None:
                raise HTTPException(
                    status_code=422, detail="An added source requires prepared input."
                )
            resolved.append((source, base, item.content, prepared))

        now = datetime.now(UTC)
        next_number = session.scalar(
            select(func.max(TaskVersion.number)).where(TaskVersion.task_id == task.id)
        )
        version = TaskVersion(task_id=task.id, number=(next_number or 0) + 1, created_at=now)
        session.add(version)
        session.flush()
        changed: list[UUID] = []
        for position, (source, base, content, prepared) in enumerate(resolved):
            revision = base
            if prepared is not None:
                if base is None:
                    session.add(source)
                    session.flush()
                normalized = normalize_source_content(
                    title=content.title if content is not None else prepared.title or "",
                    body=content.body if content is not None else prepared.body or "",
                    provenance=(
                        content.provenance if content is not None else prepared.provenance
                    ),
                )
                content_hash = _hash(asdict(normalized))
                if base is None or content_hash != base.content_hash:
                    revision = SourceRevision(
                        source_id=source.id,
                        source_preparation_id=prepared.id,
                        title=normalized.title,
                        body=normalized.body,
                        provenance=normalized.provenance,
                        content_hash=content_hash,
                        created_at=now,
                    )
                    session.add(revision)
                    session.flush()
                    prepared.confirmed_task_id = task.id
                    changed.append(revision.id)
            elif content is not None:
                assert base is not None
                normalized = normalize_source_content(
                    title=content.title, body=content.body, provenance=content.provenance
                )
                content_hash = _hash(asdict(normalized))
                if content_hash != base.content_hash:
                    revision = SourceRevision(
                        source_id=source.id,
                        source_preparation_id=base.source_preparation_id,
                        title=normalized.title,
                        body=normalized.body,
                        provenance=normalized.provenance,
                        content_hash=content_hash,
                        created_at=now,
                    )
                    session.add(revision)
                    session.flush()
                    changed.append(revision.id)
            assert revision is not None
            session.add(
                TaskVersionSource(
                    task_version_id=version.id,
                    source_revision_id=revision.id,
                    position=position,
                )
            )
        structural_change = [item.source_id for item in request.sources] != [
            revision.source_id for revision in base_revisions
        ]
        if not changed and not structural_change:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No source changes were staged.",
            )
        task.current_version_id = version.id
        record_task_activity(task, at=now)
        edit.status = "saved"
        edit.save_idempotency_key = key
        edit.save_request_hash = request_hash
        edit.saved_version_id = version.id
        edit.updated_at = now
        # Only the 来源 that changed. An unchanged one keeps the 知言报告 bound to
        # its Revision, so saving an edit costs what was edited and nothing else.
        hold_zhiyan_batch(
            session,
            user.id,
            [
                revision
                for revision in (
                    session.get(SourceRevision, revision_id) for revision_id in changed
                )
                if revision is not None
            ],
            model=settings.zhiyan_model,
        )
        session.commit()
        queue_initial_runs(
            database,
            dispatcher,
            source_revision_ids=changed,
            owner_id=user.id,
            model=settings.zhiyan_model,
        )
        return _snapshot(session, task, version)

    @router.post(
        "/tasks/{task_id}/versions/{version_id}/restore",
        response_model=TaskVersionSnapshot,
        operation_id="restore_task_version",
        tags=["source editing"],
    )
    def restore_version(
        task_id: UUID,
        version_id: UUID,
        _: RestoreVersionRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskVersionSnapshot:
        task = _owned_task(session, task_id, user.id, for_update=True)
        version = session.scalar(
            select(TaskVersion).where(TaskVersion.id == version_id, TaskVersion.task_id == task.id)
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Task version not found.")
        if task.current_version_id is not None and _has_active_runs(
            session, task.current_version_id
        ):
            raise HTTPException(status_code=409, detail=ACTIVE_RUN_BLOCK)
        task.current_version_id = version.id
        record_task_activity(task)
        session.commit()
        return _snapshot(session, task, version, active_runs=False)

    return router
