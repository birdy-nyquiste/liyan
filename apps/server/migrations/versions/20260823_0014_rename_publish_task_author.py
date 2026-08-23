"""Hold the author the user typed, rather than one the target supplied.

Revision ID: 20260823_0014
Revises: 20260823_0013
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260823_0014"
down_revision = "20260823_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode so SQLite, which cannot rename a column in place, rebuilds the
    # table instead.
    with op.batch_alter_table("publish_tasks") as batch:
        batch.alter_column(
            "target_author", new_column_name="author", existing_type=sa.String(length=255)
        )


def downgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.alter_column(
            "author", new_column_name="target_author", existing_type=sa.String(length=255)
        )
