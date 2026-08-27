"""Whether a user can pay for the work they are asking for.

A sibling of `execution_limits`, and deliberately not the same thing. That one
asks whether a user is already holding too much of a shared queue, and answers
429 — wait, and it will pass. This one asks whether they can afford what they
are starting, and answers 402 — buy 额度, and it will pass. Two different
refusals with two different remedies, and folding them together would tell a
user to wait for something waiting cannot fix.

Called at the entry points that start work rather than wired in as a dependency,
for the reasons `execution_limits` gives at length: the entry points do not agree
on when to ask, and a blanket dependency would have to be turned off in more
places than it applied.

No figure is ever quoted. The estimate exists to answer one question — does this
begin, or is the user told there is not enough — and a quoted price invites the
arithmetic that follows it, when a 预扣 settles down and rarely to the quoted
number. `docs/design/credits-in-the-workbench.md` argues that at length.
"""

from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from liyan_server import credits
from liyan_server.credits import hold
from liyan_server.database import SourceRevision
from liyan_server.liyan.runs import LIYAN_TARGET_TYPE
from liyan_server.rate_card import estimate_liyan_credits, estimate_zhiyan_credits
from liyan_server.zhiyan.orchestration import accepted_report
from liyan_server.zhiyan.runs import ZHIYAN_TARGET_TYPE

INSUFFICIENT_MESSAGE = "额度不足，购买后可继续。"

#: URL and file 来源 are what a 付费用户 buys. The workbench shows both as locked
#: rather than hiding them, so reaching this is a client going around the
#: interface rather than a user meeting a wall.
PAID_ONLY_MESSAGE = "公共文章链接与上传文件需购买额度后解锁。"


def refuse_when_short(session: Session, owner_id: UUID, *, needed: int) -> None:
    """Refuse work this user cannot pay for, without saying by how much.

    402 rather than 429: this is not a queue to wait out. The remedy is a
    purchase, and `Retry-After` would name a moment at which nothing will have
    changed.
    """
    if credits.remaining(session, owner_id) >= needed:
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=INSUFFICIENT_MESSAGE,
    )


def refuse_unless_paid(session: Session, owner_id: UUID) -> None:
    """Refuse the 来源 kinds that belong to a 付费用户.

    The boundary is mostly structural rather than policed: a pasted 来源 queues
    no Execution at all, so a user who has never bought 额度 never reaches
    Chromium or the file parser by any path the interface offers. This is the
    backstop for the paths it does not.
    """
    if credits.has_purchased(session, owner_id):
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=PAID_ONLY_MESSAGE,
    )


def hold_zhiyan_batch(
    session: Session,
    owner_id: UUID,
    revisions: Sequence[SourceRevision],
    *,
    model: str,
) -> None:
    """预扣 for every 来源 one act will analyze, or refuse the act.

    Whole, or not at all. Confirming a 任务创建会话 with three 来源 is one thing a
    user did, and admitting two of them would leave a 任务版本 with one report and
    two 来源 nobody will ever analyze — the half-analyzed version
    `execution_limits` refuses to create, arrived at through the ledger instead
    of the queue.

    Called inside the transaction that creates the 任务版本 rather than beside
    `queue_initial_runs`, which deliberately runs after that transaction
    commits. Holding there would let two confirmations both pass this check and
    the second run out partway through its 来源.

    Skips 来源 that already hold a report: re-analysis is free because there is
    nothing to analyze again, which is the same rule `queue_initial_runs`
    applies to the work itself.
    """
    wanted = [
        (revision.id, estimate_zhiyan_credits(source_characters=len(revision.body), model=model))
        for revision in revisions
        if accepted_report(session, revision.id) is None
    ]
    if not wanted:
        return
    refuse_when_short(session, owner_id, needed=sum(estimate for _, estimate in wanted))
    for revision_id, estimate in wanted:
        hold(
            session,
            owner_id,
            target_type=ZHIYAN_TARGET_TYPE,
            target_id=revision_id,
            attempt=1,
            credits=estimate,
        )


def hold_zhiyan_attempt(
    session: Session,
    owner_id: UUID,
    revision: SourceRevision,
    *,
    attempt: int,
    model: str,
) -> None:
    """预扣 for one 知言 run, when a user asks for it again themselves.

    One hold per attempt rather than per 来源: the attempt before it settled at
    whatever it cost, which for a failed run is nothing. A user pays once for
    one 知言报告 however many tries it took to get one.
    """
    estimate = estimate_zhiyan_credits(source_characters=len(revision.body), model=model)
    refuse_when_short(session, owner_id, needed=estimate)
    hold(
        session,
        owner_id,
        target_type=ZHIYAN_TARGET_TYPE,
        target_id=revision.id,
        attempt=attempt,
        credits=estimate,
    )


def hold_liyan_attempt(
    session: Session,
    owner_id: UUID,
    article_id: UUID,
    *,
    attempt: int,
    input_characters: int,
    model: str,
) -> None:
    """预扣 for one 立言 generation.

    Every generation is charged, including a regeneration with a new 立言指令.
    Unlike a 知言报告 — which is immutable and bound to one source Revision, so
    asking for it twice returns the one that exists — an article is produced
    afresh each time, and the provider is paid afresh each time.
    """
    estimate = estimate_liyan_credits(input_characters=input_characters, model=model)
    refuse_when_short(session, owner_id, needed=estimate)
    hold(
        session,
        owner_id,
        target_type=LIYAN_TARGET_TYPE,
        target_id=article_id,
        attempt=attempt,
        credits=estimate,
    )
