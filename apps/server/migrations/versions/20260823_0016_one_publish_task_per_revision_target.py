"""Let one Revision reach one 发布目标 at most once.

Blog v0.11 offers no idempotency key and no Preview lookup, so a duplicate
Preview could never be found afterwards. The pair is made unique here rather
than only in the API, because an API check alone loses the race.

Revision ID: 20260823_0016
Revises: 20260823_0015
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260823_0016"
down_revision = "20260823_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _refuse_existing_duplicates()
    with op.batch_alter_table("publish_tasks") as batch:
        batch.create_unique_constraint(
            "uq_publish_tasks_revision_target", ["revision_id", "target_key"]
        )


def _refuse_existing_duplicates() -> None:
    """Stop with an answerable message rather than an opaque constraint error.

    A database written before this rule may hold two 发布任务 for one pair. They
    are publication evidence, so this migration will not choose one to delete —
    it names them and leaves the decision to whoever knows what reached Blog.
    """
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT revision_id, target_key, COUNT(*) AS total FROM publish_tasks "
            "GROUP BY revision_id, target_key HAVING COUNT(*) > 1"
        )
    ).all()
    if not duplicates:
        return
    listed = ", ".join(f"{row.revision_id}/{row.target_key} ({row.total})" for row in duplicates)
    raise RuntimeError(
        "publish_tasks already holds more than one 发布任务 for a Revision and "
        f"发布目标 pair, so the new uniqueness cannot be applied: {listed}. "
        "Decide which submission is the real one before migrating; this "
        "migration will not delete publication evidence."
    )


def downgrade() -> None:
    with op.batch_alter_table("publish_tasks") as batch:
        batch.drop_constraint("uq_publish_tasks_revision_target", type_="unique")
