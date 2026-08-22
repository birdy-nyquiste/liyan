"""Create local users mapped from verified Supabase subjects.

Revision ID: 20260822_0002
Revises: 20260822_0001
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0002"
down_revision = "20260822_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auth_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_auth_subject", "users", ["auth_subject"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_auth_subject", table_name="users")
    op.drop_table("users")
