"""Add durable history visibility and cleanup jobs for M3.

Revision ID: 0005_m3_read_cleanup
Revises: 0004_m3_recovery
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_m3_read_cleanup"
down_revision = "0004_m3_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("deleted_at", sa.String(), nullable=True))
        batch.add_column(
            sa.Column(
                "warning_codes_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )
    op.create_index(
        "idx_runs_history",
        "runs",
        ["deleted_at", "status", "created_at", "id"],
    )
    op.create_table(
        "run_cleanup_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "idx_run_cleanup_claim",
        "run_cleanup_jobs",
        ["status", "lease_expires_at", "created_at"],
    )
    op.execute("PRAGMA user_version = 5")


def downgrade() -> None:
    op.drop_index("idx_run_cleanup_claim", table_name="run_cleanup_jobs")
    op.drop_table("run_cleanup_jobs")
    op.drop_index("idx_runs_history", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("warning_codes_json")
        batch.drop_column("deleted_at")
    op.execute("PRAGMA user_version = 4")
