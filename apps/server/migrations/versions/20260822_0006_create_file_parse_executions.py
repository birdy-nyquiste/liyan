"""Create uploaded-file preparations and deterministic parse results.

Revision ID: 20260822_0006
Revises: 20260822_0005
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0006"
down_revision = "20260822_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch:
        batch.drop_constraint("fk_executions_result_id", type_="foreignkey")
    with op.batch_alter_table("source_preparations") as batch:
        batch.drop_constraint("fk_source_preparations_accepted_result_id", type_="foreignkey")
        batch.alter_column("input_url", existing_type=sa.Text(), nullable=True)
        batch.alter_column("normalized_url", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("filename", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("content_type", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("object_key", sa.Text(), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.create_table(
        "file_parse_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("input_identity", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id"),
    )


def downgrade() -> None:
    op.drop_table("file_parse_results")
    with op.batch_alter_table("source_preparations") as batch:
        batch.drop_column("size_bytes")
        batch.drop_column("content_hash")
        batch.drop_column("object_key")
        batch.drop_column("content_type")
        batch.drop_column("filename")
        batch.alter_column("normalized_url", existing_type=sa.Text(), nullable=False)
        batch.alter_column("input_url", existing_type=sa.Text(), nullable=False)
        batch.create_foreign_key(
            "fk_source_preparations_accepted_result_id",
            "url_fetch_results",
            ["accepted_result_id"],
            ["id"],
        )
    with op.batch_alter_table("executions") as batch:
        batch.create_foreign_key(
            "fk_executions_result_id", "url_fetch_results", ["result_id"], ["id"]
        )
