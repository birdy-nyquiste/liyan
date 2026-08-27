"""What a user has left, and every way it moves.

The balance is `SUM(amount)` and is stored nowhere. A cached total would be a
second source of truth for money, and the copy that drifts is the one nobody
notices until somebody is refused work they paid for. A user's ledger is a few
rows per 立言任务, so the sum stays cheap for a long time; when it stops being
cheap, cache it somewhere that cannot be mistaken for the record.

Every writer is safe to call twice. The partial unique indexes on
`credit_entries` are what actually enforce that — so a settlement written both
eagerly by a worker and again by the reconciling sweep collides rather than
counting twice — and these functions check first so the common case is not an
exception.

Nothing here decides *whether* work may start. That belongs at the entry points
that start it, beside `refuse_when_at_capacity`, for the reasons its docstring
gives.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from liyan_server.database import CreditEntry
from liyan_server.execution_states import CreditEntryKind

#: What a capture charge is recorded against — the same `target_type` an
#: Execution uses for a fetch or a parse, so one 来源's charge and the work it
#: paid for point at the same row.
SOURCE_PREPARATION = "source_preparation"


def remaining(session: Session, owner_id: UUID) -> int:
    """How much 额度 this user has, which is the only figure they are shown.

    It can be negative, but only through a clawback: no 预扣 is admitted that
    exceeds the balance, so spending cannot take it below zero. An unpaid
    balance is a debt rather than a spend, and it should be visible as one.
    """
    return int(
        session.scalar(
            select(func.coalesce(func.sum(CreditEntry.amount), 0)).where(
                CreditEntry.owner_id == owner_id
            )
        )
        or 0
    )


def has_purchased(session: Session, owner_id: UUID) -> bool:
    """Whether this user is a 付费用户, which is what authorizes URL and file 来源.

    Derived rather than stored. It is not a plan, a tier, or a subscription:
    there is nothing to keep in sync, and nothing that can disagree with the
    ledger.
    """
    return (
        session.scalar(
            select(CreditEntry.id)
            .where(CreditEntry.owner_id == owner_id, CreditEntry.kind == "purchase")
            .limit(1)
        )
        is not None
    )


def _existing(
    session: Session,
    *,
    kind: CreditEntryKind,
    target_type: str,
    target_id: UUID,
    attempt: int | None = None,
) -> CreditEntry | None:
    statement = select(CreditEntry).where(
        CreditEntry.kind == kind,
        CreditEntry.target_type == target_type,
        CreditEntry.target_id == target_id,
    )
    if attempt is not None:
        statement = statement.where(CreditEntry.attempt == attempt)
    return session.scalar(statement)


def _add(
    session: Session,
    owner_id: UUID,
    *,
    kind: CreditEntryKind,
    amount: int,
    now: datetime | None = None,
    **columns: object,
) -> CreditEntry:
    entry = CreditEntry(
        owner_id=owner_id,
        kind=kind,
        amount=amount,
        created_at=now or datetime.now(UTC),
        **columns,
    )
    session.add(entry)
    session.flush()
    return entry


def grant(
    session: Session, owner_id: UUID, amount: int, *, now: datetime | None = None
) -> CreditEntry:
    """赠送额度 — what a new user is given once, and any later promotion."""
    return _add(session, owner_id, kind="grant", amount=abs(amount), now=now)


def purchase(
    session: Session,
    owner_id: UUID,
    amount: int,
    *,
    stripe_event_id: str,
    now: datetime | None = None,
) -> CreditEntry | None:
    """购买额度, keyed to the Stripe event that paid for them.

    Returns nothing when that event has already been credited. Stripe retries
    webhooks, and fulfilling one twice is the most expensive mistake available
    here, so the event id is the key and a redelivery finds its own row.
    """
    already = session.scalar(
        select(CreditEntry).where(CreditEntry.stripe_event_id == stripe_event_id)
    )
    if already is not None:
        return None
    return _add(
        session,
        owner_id,
        kind="purchase",
        amount=abs(amount),
        now=now,
        stripe_event_id=stripe_event_id,
    )


def charge_capture(
    session: Session,
    owner_id: UUID,
    *,
    preparation_id: UUID,
    credits: int,
    now: datetime | None = None,
) -> CreditEntry | None:
    """The flat fee one 来源 costs, taken outright rather than held.

    Capture is the one act whose price is known before it runs, so there is
    nothing to estimate and nothing to settle. Returns nothing if this 来源 has
    already been charged, which is what makes a replayed intake free.
    """
    if _existing(
        session, kind="capture", target_type=SOURCE_PREPARATION, target_id=preparation_id
    ):
        return None
    return _add(
        session,
        owner_id,
        kind="capture",
        amount=-abs(credits),
        now=now,
        target_type=SOURCE_PREPARATION,
        target_id=preparation_id,
    )


def hold(
    session: Session,
    owner_id: UUID,
    *,
    target_type: str,
    target_id: UUID,
    attempt: int,
    credits: int,
    now: datetime | None = None,
) -> CreditEntry | None:
    """预扣 — 额度 taken when work is admitted, at what it is expected to cost.

    Keyed to the target rather than to an Execution, because a 知言 run's 预扣 is
    taken inside the transaction that confirms a 任务创建会话 — before the
    Execution it pays for exists.
    """
    if _existing(
        session, kind="hold", target_type=target_type, target_id=target_id, attempt=attempt
    ):
        return None
    return _add(
        session,
        owner_id,
        kind="hold",
        amount=-abs(credits),
        now=now,
        target_type=target_type,
        target_id=target_id,
        attempt=attempt,
    )


def settle(
    session: Session,
    owner_id: UUID,
    *,
    target_type: str,
    target_id: UUID,
    attempt: int,
    actual: int,
    execution_id: UUID | None = None,
    now: datetime | None = None,
) -> CreditEntry | None:
    """结算 — the correction once the work is done and its cost is known.

    Positive when the estimate was high, returning the excess; negative when it
    was low, collecting the shortfall. Work that produced nothing settles at
    zero, so the whole 预扣 comes back: a user never pays for a run that gave
    them nothing.

    Returns nothing when there was no 预扣 to correct, or when this attempt has
    already settled — the second being how the eager path and the reconciling
    sweep stay safe together.
    """
    held = _existing(
        session, kind="hold", target_type=target_type, target_id=target_id, attempt=attempt
    )
    if held is None:
        return None
    if _existing(
        session, kind="settle", target_type=target_type, target_id=target_id, attempt=attempt
    ):
        return None
    return _add(
        session,
        owner_id,
        kind="settle",
        amount=abs(held.amount) - max(0, actual),
        now=now,
        target_type=target_type,
        target_id=target_id,
        attempt=attempt,
        execution_id=execution_id,
    )


def clawback(
    session: Session,
    owner_id: UUID,
    amount: int,
    *,
    stripe_event_id: str,
    now: datetime | None = None,
) -> CreditEntry | None:
    """额度 reclaimed by a refund or a payment dispute.

    The only movement allowed to take a balance below zero. What is left is a
    debt rather than a spend, and hiding it at zero would let the same person
    start again for free.
    """
    already = session.scalar(
        select(CreditEntry).where(CreditEntry.stripe_event_id == stripe_event_id)
    )
    if already is not None:
        return None
    return _add(
        session,
        owner_id,
        kind="clawback",
        amount=-abs(amount),
        now=now,
        stripe_event_id=stripe_event_id,
    )
