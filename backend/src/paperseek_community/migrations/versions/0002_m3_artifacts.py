"""Add durable artifact references for M3.

Revision ID: 0002_m3_artifacts
Revises: 0001_m1_run_vertical
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_m3_artifacts"
down_revision = "0001_m1_run_vertical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name="ck_run_artifacts_sha256"),
        sa.CheckConstraint("size >= 0", name="ck_run_artifacts_size"),
        sa.UniqueConstraint(
            "run_id",
            "kind",
            "schema_version",
            "filename",
            name="uq_run_artifact_logical_key",
        ),
    )
    op.create_index(
        "idx_run_artifacts_list",
        "run_artifacts",
        ["run_id", "visibility", "kind"],
    )
    with op.batch_alter_table("run_checkpoints") as batch:
        batch.add_column(sa.Column("state_artifact_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_run_checkpoints_state_artifact",
            "run_artifacts",
            ["state_artifact_id"],
            ["id"],
        )
    with op.batch_alter_table("run_results") as batch:
        batch.add_column(sa.Column("record_artifact_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_run_results_record_artifact",
            "run_artifacts",
            ["record_artifact_id"],
            ["id"],
        )
    op.execute("PRAGMA user_version = 2")


def downgrade() -> None:
    with op.batch_alter_table("run_results") as batch:
        batch.drop_constraint("fk_run_results_record_artifact", type_="foreignkey")
        batch.drop_column("record_artifact_id")
    with op.batch_alter_table("run_checkpoints") as batch:
        batch.drop_constraint("fk_run_checkpoints_state_artifact", type_="foreignkey")
        batch.drop_column("state_artifact_id")
    op.drop_index("idx_run_artifacts_list", table_name="run_artifacts")
    op.drop_table("run_artifacts")
    op.execute("PRAGMA user_version = 1")
