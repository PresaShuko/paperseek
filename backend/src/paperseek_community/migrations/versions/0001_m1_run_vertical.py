"""Create the M1 durable run vertical-slice tables.

Revision ID: 0001_m1_run_vertical
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_m1_run_vertical"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("current_step", sa.String(), nullable=False, server_default=""),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workflow_version", sa.String(), nullable=False),
        sa.Column("engine_version", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("config_schema_version", sa.Integer(), nullable=False),
        sa.Column("artifact_schema_version", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("idx_runs_claim", "runs", ["status", "lease_expires_at"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_events_sequence"),
    )
    op.create_index("idx_run_events_replay", "run_events", ["run_id", "sequence"])

    op.create_table(
        "run_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_key", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("workflow_version", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uq_run_checkpoint_idempotency"),
    )
    op.create_index(
        "idx_run_checkpoints_latest",
        "run_checkpoints",
        ["run_id", "event_sequence"],
    )

    op.create_table(
        "run_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", "rank", name="uq_run_results_rank"),
    )
    op.execute("PRAGMA user_version = 1")


def downgrade() -> None:
    op.drop_table("run_results")
    op.drop_index("idx_run_checkpoints_latest", table_name="run_checkpoints")
    op.drop_table("run_checkpoints")
    op.drop_index("idx_run_events_replay", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("idx_runs_claim", table_name="runs")
    op.drop_table("runs")
    op.execute("PRAGMA user_version = 0")
