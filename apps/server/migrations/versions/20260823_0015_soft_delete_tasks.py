"""Soft delete task aggregates while publication evidence remains independent.

Revision ID: 20260823_0015
Revises: 20260823_0014
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260823_0015"
down_revision = "20260823_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_tasks_deleted_at", ["deleted_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_deleted_at")
        batch.drop_column("deleted_at")
