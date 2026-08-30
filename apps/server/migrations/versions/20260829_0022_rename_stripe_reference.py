"""Key a Stripe-backed 额度 entry to the payment, not to the delivery.

`stripe_event_id` assumed one event is one movement of money. It is not. A
Checkout Session settling through Alipay or WeChat Pay produces
`checkout.session.completed` and then `checkout.session.async_payment_succeeded`
— two events, two ids, one payment — and a purchase keyed on the event id would
credit whichever ones were fulfilled. A partial refund is worse: every
`charge.refunded` carries the *cumulative* `amount_refunded`, so two partial
refunds keyed on their event ids claw back the first amount twice.

So the column keeps its job — the thing that makes an entry idempotent — and
loses the claim that the thing is always an event:

    购买      pi_xxx
    clawback  pi_xxx#refunded:1500        (cumulative cents, so a repeat collides)
              pi_xxx#dispute:du_xxx

Sharing the `pi_xxx` prefix is also what lets a refund find the 购买 it reverses
and what a user still holds of it, without a second column pointing sideways.

Values are carried across rather than rewritten. No code path has ever written
this column — fulfillment is what would have, and it did not exist until now —
so anything in it was put there by hand. A local `evt_local_backfill_…` 购买,
made to become a 付费用户 during development, is the shape that has turned up.

Such a row keeps its balance and its 付费用户 standing, and the only thing it
loses is the ability to be refunded: a clawback finds its 购买 by PaymentIntent,
and no payment backs a row somebody wrote themselves. That is the right outcome
rather than a gap to paper over — inventing a `pi_…` for it would make a
hand-made row look like money that had actually moved.

Revision ID: 20260829_0022
Revises: 20260827_0021
Create Date: 2026-08-29
"""

from alembic import op
from sqlalchemy import text

revision = "20260829_0022"
down_revision = "20260827_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_credit_entries_stripe_event", table_name="credit_entries")
    op.alter_column("credit_entries", "stripe_event_id", new_column_name="stripe_reference")
    # Still the only thing standing between a redelivered webhook and a second
    # credit, which is the most expensive mistake this table can make.
    op.create_index(
        "uq_credit_entries_stripe_reference",
        "credit_entries",
        ["stripe_reference"],
        unique=True,
        postgresql_where=text("stripe_reference IS NOT NULL"),
        sqlite_where=text("stripe_reference IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_credit_entries_stripe_reference", table_name="credit_entries")
    op.alter_column("credit_entries", "stripe_reference", new_column_name="stripe_event_id")
    op.create_index(
        "uq_credit_entries_stripe_event",
        "credit_entries",
        ["stripe_event_id"],
        unique=True,
        postgresql_where=text("stripe_event_id IS NOT NULL"),
        sqlite_where=text("stripe_event_id IS NOT NULL"),
    )
