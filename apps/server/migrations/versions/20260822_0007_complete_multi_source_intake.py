"""Prevent confirmed preparation sources from being consumed twice.

Revision ID: 20260822_0007
Revises: 20260822_0006
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0007"
down_revision = "20260822_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_preparations") as batch:
        batch.add_column(sa.Column("confirmed_task_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_source_preparations_confirmed_task_id",
            "tasks",
            ["confirmed_task_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_source_preparations_confirmed_task_id",
            ["confirmed_task_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("source_preparations") as batch:
        batch.drop_index("ix_source_preparations_confirmed_task_id")
        batch.drop_constraint("fk_source_preparations_confirmed_task_id", type_="foreignkey")
        batch.drop_column("confirmed_task_id")
