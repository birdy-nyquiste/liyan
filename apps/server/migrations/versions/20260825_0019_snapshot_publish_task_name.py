"""Keep the task name in publication audit history.

Revision ID: 20260825_0019
Revises: 20260825_0018
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0019"
down_revision = "20260825_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.add_column(sa.Column("task_display_name", sa.String(length=255), nullable=True))
    op.execute(
        """
        UPDATE publish_tasks
        SET task_display_name = COALESCE(
            (SELECT tasks.display_name FROM tasks WHERE tasks.id = publish_tasks.task_id),
            '任务'
        )
        """
    )
    with op.batch_alter_table("publish_tasks") as batch:
        batch.alter_column("task_display_name", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.drop_column("task_display_name")
