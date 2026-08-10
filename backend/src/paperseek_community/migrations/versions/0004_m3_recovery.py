"""Add the durable run deadline required for M3 recovery.

Revision ID: 0004_m3_recovery
Revises: 0003_m3_cancellation
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_m3_recovery"
down_revision = "0003_m3_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("deadline_at", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE runs
        SET deadline_at = strftime(
            '%Y-%m-%dT%H:%M:%f+00:00',
            COALESCE(started_at, created_at),
            '+1 day'
        )
        WHERE deadline_at IS NULL
        """
    )
    with op.batch_alter_table("runs") as batch:
        batch.alter_column("deadline_at", existing_type=sa.String(), nullable=False)
    op.create_index(
        "idx_runs_recovery_claim",
        "runs",
        ["status", "lease_expires_at", "deadline_at", "created_at"],
    )
    op.execute("PRAGMA user_version = 4")


def downgrade() -> None:
    op.drop_index("idx_runs_recovery_claim", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("deadline_at")
    op.execute("PRAGMA user_version = 3")
