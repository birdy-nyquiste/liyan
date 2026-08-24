"""Make a silent worker observable.

A dead worker leaves queued work queued and the API answering, so nothing about
the deployment looks wrong. One row per worker, rewritten as it runs, is the
only thing that can tell "idle" from "gone".

Revision ID: 20260824_0017
Revises: 20260823_0016
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260824_0017"
down_revision = "20260823_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker", sa.String(length=255), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
