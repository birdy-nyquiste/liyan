"""Create immutable 立言文章 Revisions saved explicitly by the user.

Revision ID: 20260822_0012
Revises: 20260822_0011
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0012"
down_revision = "20260822_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "liyan_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("task_version_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("base_revision_id", sa.Uuid(), nullable=True),
        sa.Column("restored_from_revision_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["liyan_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_version_id"], ["task_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["base_revision_id"],
            ["liyan_revisions.id"],
            name="fk_liyan_revisions_base_revision_id",
        ),
        sa.ForeignKeyConstraint(
            ["restored_from_revision_id"],
            ["liyan_revisions.id"],
            name="fk_liyan_revisions_restored_from_revision_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "number", name="uq_liyan_revisions_article_number"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_liyan_revisions_owner_idempotency_key",
        ),
    )
    op.create_index("ix_liyan_revisions_owner_id", "liyan_revisions", ["owner_id"])
    op.create_index("ix_liyan_revisions_article_id", "liyan_revisions", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_liyan_revisions_article_id", table_name="liyan_revisions")
    op.drop_index("ix_liyan_revisions_owner_id", table_name="liyan_revisions")
    op.drop_table("liyan_revisions")
