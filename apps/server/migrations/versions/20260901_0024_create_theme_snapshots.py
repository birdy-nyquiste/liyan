"""Give a 任务版本 a 主题, and 知言 a second thing to analyse.

主题 is a special 来源: version-scoped, immutable, carrying one 知言报告 of its
own, and changed only by producing a new 任务版本. So it arrives as a snapshot
table rather than a column on `task_versions` — the column there is only the
pointer, and it is nullable because every version that already exists has no
主题 and none of them changes.

`theme_revisions` is unique on `(task_id, content_hash, source_context_hash)`
rather than on the text alone. A 主题知言 run reads the 来源 of its version, so
what was analysed is the pair; two versions agreeing on both share one snapshot
and therefore one report, and editing a 来源 reaches a new snapshot that owes a
new run.

`theme_proposals` is one row per press of 提炼主题 in a 任务创建会话. It exists
because `executions.target_id` is a non-null UUID under a unique index over
active runs, and a creation session is identified by a client string.

Revision ID: 20260901_0024
Revises: 20260830_0023
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260901_0024"
down_revision = "20260830_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "theme_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("content", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_context_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "task_id",
            "content_hash",
            "source_context_hash",
            name="uq_theme_revisions_identity",
        ),
    )
    with op.batch_alter_table("task_versions") as batch:
        batch.add_column(sa.Column("theme_revision_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_task_versions_theme_revision_id",
            "theme_revisions",
            ["theme_revision_id"],
            ["id"],
        )
    op.create_table(
        "theme_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Uuid(),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "theme_revision_id",
            sa.Uuid(),
            sa.ForeignKey("theme_revisions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("provider_response_id", sa.String(length=128), nullable=True),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("search_actions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "theme_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("client_session_id", sa.String(length=255), nullable=False, index=True),
        sa.Column("source_context_hash", sa.String(length=64), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("theme_proposals")
    op.drop_table("theme_reports")
    with op.batch_alter_table("task_versions") as batch:
        batch.drop_constraint("fk_task_versions_theme_revision_id", type_="foreignkey")
        batch.drop_column("theme_revision_id")
    op.drop_table("theme_revisions")
