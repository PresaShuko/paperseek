"""Add atomic public run submission records for M4.

Revision ID: 0006_m4_submission
Revises: 0005_m3_read_cleanup
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_m4_submission"
down_revision = "0005_m3_read_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("owner_subject", sa.String(), nullable=True))
    op.create_index(
        "uq_runs_active_subject",
        "runs",
        ["owner_subject"],
        unique=True,
        sqlite_where=sa.text(
            "owner_subject IS NOT NULL AND deleted_at IS NULL "
            "AND status IN ('queued', 'running', 'cancelling')"
        ),
    )
    op.create_table(
        "run_submissions",
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("subject", "idempotency_key"),
    )
    op.create_table(
        "run_credentials",
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_kind", sa.String(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "credential_kind"),
    )
    op.execute("PRAGMA user_version = 6")


def downgrade() -> None:
    op.drop_table("run_credentials")
    op.drop_table("run_submissions")
    op.drop_index("uq_runs_active_subject", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("owner_subject")
    op.execute("PRAGMA user_version = 5")
