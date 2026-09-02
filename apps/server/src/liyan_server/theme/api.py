"""The 主题 boundary: pressing 提炼主题.

Reading a 主题知言报告 is not here. A report belongs to the 知言 area of a
任务版本 and arrives with the 来源 reports, so `zhiyan/api.py` answers for it —
one request returns everything that gates 立言, which is the only way a client
cannot disagree with the server about whether it may generate.

What is here is the one act with nowhere else to live: pressing the button.
Retrying a failed analysis is a 知言 act and sits beside a 来源's retry.

A press comes from one of two places, and the difference is where its 来源 are.
In a 任务创建会话 they are rows the server captured, so the press names the
session and the server reads them. In a 来源编辑会话 they are the version's
revisions plus whatever the writer has typed over them — and that last part is
in the browser until it is saved — so the press carries them. Both are the
user's own material either way; what changes is only who can read it.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.credit_limits import hold_theme_proposal
from liyan_server.database import (
    Database,
    Execution,
    SourceEditSession,
    ThemeProposal,
    User,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_limits import refuse_when_at_capacity
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content
from liyan_server.task_creation.confirmation import SourceInput
from liyan_server.task_creation.contracts import (
    ExecutionError,
    ExecutionResponse,
    execution_response,
)
from liyan_server.task_creation.sessions import (
    normalized_body_hash,
    normalized_session_identity,
)
from liyan_server.theme.orchestration import dispatch_or_fail, load_proposal_runs
from liyan_server.theme.prompt import AnalysedSource
from liyan_server.theme.proposal import (
    ProposedSources,
    ThemeCandidate,
    proposed_sources_characters,
)
from liyan_server.theme.proposal_worker import proposed_sources
from liyan_server.theme.revisions import source_context_hash
from liyan_server.theme.runs import PROPOSAL_OPERATION, new_proposal_execution

type ProposalStatus = Literal["running", "failed", "succeeded", "cancelled"]

INCOMPLETE_SESSION_MESSAGE = "请先添加来源并等待全部抓取成功，然后再提炼主题。"
NO_SOURCES_MESSAGE = "提炼主题需要一到三个来源。"
#: What the whole press may read. Not a policy about 来源 — one 来源 may be this
#: long on its own — but a bound on what a single request may carry, since these
#: 来源 arrive in the request rather than being read from rows.
MAX_PROPOSAL_CHARACTERS = 500_000
TOO_MUCH_MESSAGE = "来源正文过长，无法一次提炼主题。"
ACTIVE_PROPOSAL_MESSAGE = "主题提炼正在进行中。"
#: The only thing a user is told about a failed press, as everywhere else.
BUSY_MESSAGE = "服务繁忙，请重试。"


class ProposeThemesRequest(BaseModel):
    #: The 任务创建会话's identity, or the 来源编辑会话's own id. Either way it is
    #: what makes two presses in one sitting one at a time.
    client_session_id: str
    #: The 来源 as the writer has them, sent only from a 来源编辑会话. Absent means
    #: "read the creation session's own 来源".
    sources: list[SourceInput] | None = None


class ThemeProposalResponse(BaseModel):
    """One press of 提炼主题, and the three candidates it produced."""

    id: str
    client_session_id: str
    status: ProposalStatus
    candidates: list[ThemeCandidate]
    execution: ExecutionResponse | None


def proposal_response(
    proposal: ThemeProposal,
    execution: Execution | None,
) -> ThemeProposalResponse:
    return ThemeProposalResponse(
        id=str(proposal.id),
        client_session_id=proposal.client_session_id,
        status=_status(proposal, execution),
        candidates=[ThemeCandidate.model_validate(candidate) for candidate in proposal.candidates],
        execution=_execution_response(execution) if execution else None,
    )


def _execution_response(execution: Execution) -> ExecutionResponse:
    response = execution_response(execution)
    if execution.status not in {"failed", "stale"}:
        return response
    return response.model_copy(
        update={"error": ExecutionError(code="busy", message=BUSY_MESSAGE)}
    )


def _status(proposal: ThemeProposal, execution: Execution | None) -> ProposalStatus:
    if proposal.candidates:
        return "succeeded"
    if execution is None:
        # A row exists only because a press created it, so its run is gone only
        # if something removed it. Reading that as failed is the safe answer:
        # the button becomes pressable again.
        return "failed"
    if execution.status in ACTIVE_EXECUTION_STATUSES:
        return "running"
    return "cancelled" if execution.status == "cancelled" else "failed"


def theme_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter()

    def owned_proposal(
        session: Session,
        *,
        proposal_id: UUID,
        owner_id: UUID,
    ) -> ThemeProposal:
        proposal = session.scalar(
            select(ThemeProposal).where(
                ThemeProposal.id == proposal_id,
                ThemeProposal.owner_id == owner_id,
            )
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Theme proposal not found.",
            )
        return proposal

    def edit_session_sources(
        session: Session,
        *,
        owner_id: UUID,
        edit_id: str,
        sources: list[SourceInput],
    ) -> ProposedSources:
        """The 来源 of a 来源编辑会话, as the writer currently has them.

        The session is looked up so this cannot be a way to have an Agent read
        arbitrary text under someone's account: a press has to belong to an
        editing session that user actually has open.
        """
        try:
            edit_uuid = UUID(edit_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source edit session not found.",
            ) from error
        edit = session.scalar(
            select(SourceEditSession).where(
                SourceEditSession.id == edit_uuid,
                SourceEditSession.owner_id == owner_id,
                SourceEditSession.status == "active",
            )
        )
        if edit is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source edit session not found.",
            )
        if not 1 <= len(sources) <= 3:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=NO_SOURCES_MESSAGE,
            )
        normalized = [
            normalize_source_content(
                title=source.title,
                body=source.body,
                provenance=source.provenance,
            )
            for source in sources
        ]
        if sum(len(source.body) for source in normalized) > MAX_PROPOSAL_CHARACTERS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=TOO_MUCH_MESSAGE,
            )
        return ProposedSources(
            client_session_id=edit_id,
            source_context_hash=source_context_hash(
                [normalized_body_hash(source.body) for source in normalized]
            ),
            sources=tuple(
                AnalysedSource(
                    title=source.title,
                    body=source.body,
                    provenance=source.provenance,
                )
                for source in normalized
            ),
        )

    @router.post(
        "/task-creation/theme-proposals",
        operation_id="propose_session_themes",
        response_model=ThemeProposalResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["theme"],
    )
    def propose_session_themes(
        request: ProposeThemesRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ThemeProposalResponse:
        """One press of 提炼主题, charged once, against the 来源 as they stand now.

        "As they stand now" means two different reads. From a 任务创建会话 the
        server reads the session's own 来源 and requires every one of them to
        have been captured. From a 来源编辑会话 the request carries them, because
        an inline edit is not a row yet.

        Pressing again replaces nothing on the server: each press is its own row,
        and the client reads the one it just created. What the *interface* does
        with the previous three candidates is its own business — they are gone
        from the screen, and the 主题 the user has typed is never touched.
        """
        client_session_id = normalized_session_identity(request.client_session_id)
        from_edit_session = request.sources is not None
        if request.sources is not None:
            proposed = edit_session_sources(
                session,
                owner_id=user.id,
                edit_id=client_session_id,
                sources=request.sources,
            )
        else:
            session_proposed = proposed_sources(
                session,
                owner_id=user.id,
                client_session_id=client_session_id,
            )
            if session_proposed is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=INCOMPLETE_SESSION_MESSAGE,
                )
            proposed = session_proposed
        active = session.scalar(
            select(Execution)
            .join(ThemeProposal, ThemeProposal.id == Execution.target_id)
            .where(
                ThemeProposal.owner_id == user.id,
                ThemeProposal.client_session_id == client_session_id,
                Execution.operation == PROPOSAL_OPERATION,
                Execution.status.in_(ACTIVE_EXECUTION_STATUSES),
            )
        )
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ACTIVE_PROPOSAL_MESSAGE,
            )
        refuse_when_at_capacity(session, settings, owner_id=user.id)
        now = datetime.now(UTC)
        proposal = ThemeProposal(
            owner_id=user.id,
            client_session_id=client_session_id,
            source_context_hash=proposed.source_context_hash,
            candidates=[],
            created_at=now,
            updated_at=now,
        )
        session.add(proposal)
        session.flush()
        hold_theme_proposal(
            session,
            user.id,
            proposal.id,
            source_characters=proposed_sources_characters(proposed),
            model=settings.zhiyan_model,
        )
        execution = new_proposal_execution(
            proposal,
            sources=[
                (source.title, source.body, source.provenance)
                for source in proposed.sources
            ],
            session_sources=not from_edit_session,
            model=settings.zhiyan_model,
            attempt=1,
            created_at=now,
        )
        session.add(execution)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ACTIVE_PROPOSAL_MESSAGE,
            ) from error
        dispatch_or_fail(database, dispatcher, execution.id, operation=PROPOSAL_OPERATION)
        session.expire_all()
        proposal = owned_proposal(session, proposal_id=proposal.id, owner_id=user.id)
        return proposal_response(proposal, load_proposal_runs(session, proposal.id).latest)

    @router.get(
        "/task-creation/theme-proposals/{proposal_id}",
        operation_id="get_theme_proposal",
        response_model=ThemeProposalResponse,
        tags=["theme"],
    )
    def get_theme_proposal(
        proposal_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ThemeProposalResponse:
        proposal = owned_proposal(session, proposal_id=proposal_id, owner_id=user.id)
        return proposal_response(proposal, load_proposal_runs(session, proposal.id).latest)

    return router
