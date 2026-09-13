"""Let a running 知言 run say what it has done so far.

A 知言 run takes three to six minutes and, until now, put nothing on screen for
any of them. `status` was the whole of what the workbench could say, and
`running` is the same word for a run that has opened twenty pages and a run
whose worker died four minutes ago — which is why the first question anybody
asks about a slow report is whether it is still alive.

The provider can answer it. Streaming the Responses API (ADR-0004) announces
each `web_search_call` as it completes, ahead of the report by two minutes in
the run this was measured on, and these two columns are where the worker leaves
that count for the poll to pick up.

Null rather than zero, and no backfill. A run that has not reported yet and a
run that searched nothing are different states, only one of them is worth
showing, and every Execution that already exists is in neither — it is
finished, and what it did is on its report.

Revision ID: 20260912_0026
Revises: 20260910_0025
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0026"
down_revision = "20260910_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("searched_count", sa.Integer(), nullable=True))
    op.add_column("executions", sa.Column("opened_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("executions", "opened_count")
    op.drop_column("executions", "searched_count")
