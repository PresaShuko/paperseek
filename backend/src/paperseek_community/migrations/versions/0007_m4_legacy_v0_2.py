"""Add the one-time Community v0.2 migration ledger.

Revision ID: 0007_m4_legacy_v0_2
Revises: 0006_m4_submission
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_m4_legacy_v0_2"
down_revision = "0006_m4_submission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("legacy_run_id", sa.String(), nullable=True))
    op.create_index("idx_runs_legacy_run_id", "runs", ["legacy_run_id"])
    op.create_table(
        "legacy_migration_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_legacy_source_sha256"),
        sa.CheckConstraint("length(backup_sha256) = 64", name="ck_legacy_backup_sha256"),
    )
    op.create_table(
        "legacy_migration_runs",
        sa.Column(
            "batch_id",
            sa.String(),
            sa.ForeignKey("legacy_migration_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legacy_run_id", sa.String(), nullable=False),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("batch_id", "legacy_run_id"),
    )
    op.execute("PRAGMA user_version = 7")


def downgrade() -> None:
    op.drop_table("legacy_migration_runs")
    op.drop_table("legacy_migration_batches")
    op.drop_index("idx_runs_legacy_run_id", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("legacy_run_id")
    op.execute("PRAGMA user_version = 6")
