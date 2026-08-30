"""What a user is shown of their own 额度.

Two reads and nothing else. Buying is Stripe's, and spending happens wherever
work is started — this is only the account looking at itself.

No estimate is ever returned. A quoted price invites the arithmetic that follows
it, and a 预扣 settles down and rarely to the number quoted, so the estimate
stays server-side and answers one question: does this work begin, or is the user
told there is not enough. `docs/design/credits-in-the-workbench.md` argues it at
length.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server import credits
from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    CreditEntry,
    Database,
    Execution,
    LiyanArticle,
    Source,
    SourcePreparation,
    SourceRevision,
    TaskVersion,
    User,
)
from liyan_server.execution_states import TERMINAL_EXECUTION_STATUSES

#: How many 使用记录 rows one page carries. Enough that a user sees the run they
#: just started without asking for more.
PAGE = 50

type ActivityStatus = Literal["running", "done", "failed", "none"]


class AccountResponse(BaseModel):
    #: The only 额度 figure a user is shown. Their remaining balance, whole.
    remaining_credits: int
    #: Whether URL and file 来源 are theirs to submit. Derived from the ledger,
    #: never stored, so nothing can disagree with it.
    is_paying_user: bool


class UsageEntry(BaseModel):
    id: str
    kind: str
    #: What this act was — 来源抓取, 知言报告, 立言文章 — and nothing about what it
    #: was on. The 立言任务 it belongs to is a link rather than a title.
    description: str
    #: Where this leads, when it still leads anywhere. Absent once the 立言任务
    #: has been deleted: the ledger outlives it.
    task_id: str | None
    status: ActivityStatus
    #: Signed, and already net of any 结算 — what the balance actually moved by.
    #: A 预扣 still running shows as the whole of it, because that is what the
    #: balance has done so far; the correction lands when the work ends.
    amount: int
    happened_at: datetime


class UsageResponse(BaseModel):
    entries: list[UsageEntry]
    has_more: bool


#: What each act is called, in the same words the rest of the product uses for
#: it. `CONTEXT.md` defines them; the account page should not invent its own.
_LABELS = {
    "grant": "赠送额度",
    "purchase": "购买额度",
    "clawback": "额度退回",
    "capture": "来源抓取",
}

_TARGET_LABELS = {
    credits.SOURCE_PREPARATION: "来源抓取",
    "source_revision": "知言报告",
    "liyan_article": "立言文章",
}


def _label(entry: CreditEntry) -> str:
    """What this act was.

    The name alone, without the 来源 it was about: a row that read 分析来源《…》
    named the thing twice over, once in words this product does not use, and the
    title it appended is better reached by going there.
    """
    if entry.target_type:
        return _TARGET_LABELS.get(entry.target_type, "额度变动")
    return _LABELS.get(entry.kind, "额度变动")


def _task_id(session: Session, entry: CreditEntry) -> str | None:
    """The 立言任务 this act belongs to, so the row can lead back to it.

    Every hop can miss. `cleanup` removes 立言任务 and cascades into their 来源
    while these rows are deliberately kept, so a 使用记录 older than a deleted
    task simply stops being a link rather than becoming a broken one.
    """
    if entry.target_id is None:
        return None
    if entry.target_type == credits.SOURCE_PREPARATION:
        preparation = session.get(SourcePreparation, entry.target_id)
        if preparation is None or preparation.confirmed_task_id is None:
            return None
        return str(preparation.confirmed_task_id)
    if entry.target_type == "source_revision":
        revision = session.get(SourceRevision, entry.target_id)
        source = session.get(Source, revision.source_id) if revision else None
        return str(source.task_id) if source else None
    if entry.target_type == "liyan_article":
        article = session.get(LiyanArticle, entry.target_id)
        version = session.get(TaskVersion, article.task_version_id) if article else None
        return str(version.task_id) if version else None
    return None


def _status(session: Session, entry: CreditEntry, settled: bool) -> ActivityStatus:
    """Whether the work this paid for has finished, and how.

    A 预扣 with no 结算 is work still going: the 额度 are committed and the number
    a user sees is already smaller, so the row has to say why rather than look
    like a charge for nothing.
    """
    if entry.kind != "hold":
        return "none"
    if not settled:
        return "running"
    execution = session.scalar(
        select(Execution).where(
            Execution.target_type == entry.target_type,
            Execution.target_id == entry.target_id,
            Execution.input_version == entry.input_version,
            Execution.attempt == entry.attempt,
        )
    )
    if execution is None or execution.status not in TERMINAL_EXECUTION_STATUSES:
        return "failed"
    return "done" if execution.status == "succeeded" else "failed"


def account_router(database: Database, current_user: CurrentUserDependency) -> APIRouter:
    router = APIRouter(tags=["account"])

    @router.get("/account", operation_id="get_account", response_model=AccountResponse)
    def get_account(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> AccountResponse:
        return AccountResponse(
            remaining_credits=credits.remaining(session, user.id),
            is_paying_user=credits.has_purchased(session, user.id),
        )

    @router.get(
        "/account/usage",
        operation_id="list_account_usage",
        response_model=UsageResponse,
    )
    def list_account_usage(
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> UsageResponse:
        """One row per act, newest first, with its 预扣 folded into it.

        A 结算 is never its own row. On its own it reads as 额度 arriving from
        nowhere; against the 预扣 it corrects, it is the explanation for a number
        that moved and moved back — which is the whole reason this page shows
        the two together.
        """
        rows = list(
            session.scalars(
                select(CreditEntry)
                .where(CreditEntry.owner_id == user.id, CreditEntry.kind != "settle")
                .order_by(CreditEntry.created_at.desc(), CreditEntry.id.desc())
                .offset(offset)
                .limit(PAGE + 1)
            )
        )
        has_more = len(rows) > PAGE
        entries: list[UsageEntry] = []
        for entry in rows[:PAGE]:
            settlement = (
                session.scalar(
                    select(CreditEntry).where(
                        CreditEntry.kind == "settle",
                        CreditEntry.target_type == entry.target_type,
                        CreditEntry.target_id == entry.target_id,
                        CreditEntry.input_version == entry.input_version,
                        CreditEntry.attempt == entry.attempt,
                    )
                )
                if entry.kind == "hold"
                else None
            )
            entries.append(
                UsageEntry(
                    id=str(entry.id),
                    kind=entry.kind,
                    description=_label(entry),
                    task_id=_task_id(session, entry),
                    status=_status(session, entry, settlement is not None),
                    amount=entry.amount + (settlement.amount if settlement else 0),
                    happened_at=entry.created_at,
                )
            )
        return UsageResponse(entries=entries, has_more=has_more)

    return router
