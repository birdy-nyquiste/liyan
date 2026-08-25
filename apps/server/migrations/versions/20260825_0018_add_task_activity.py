"""Order task navigation by meaningful user activity.

Revision ID: 20260825_0018
Revises: 20260824_0017
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0018"
down_revision = "20260824_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE tasks SET last_activity_at = created_at")
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("last_activity_at", nullable=False)
        batch.create_index("ix_tasks_last_activity_at", ["last_activity_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_last_activity_at")
        batch.drop_column("last_activity_at")
