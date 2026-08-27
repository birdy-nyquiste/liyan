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

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from liyan_server import credits

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
