"""Independent review snapshots and versions over the durable run queue."""
from alembic import op
import sqlalchemy as sa

revision = "0008_abstract_reviews"
down_revision = "0007_m4_legacy_v0_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("kind", sa.String(), nullable=False, server_default="research"))
    op.create_index("idx_runs_kind_created", "runs", ["kind", "created_at", "id"])
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), primary_key=True),
        # Provenance only: deleting a source search must not delete the snapshot.
        sa.Column("source_run_id", sa.String(), nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
    )
    op.create_index("idx_reviews_updated", "reviews", ["updated_at", "id"])
    op.create_table(
        "review_revisions",
        sa.Column("review_id", sa.String(), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("part", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("review_id", "part", "revision"),
    )
    op.create_table(
        "review_jobs",
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("review_id", sa.String(), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.UniqueConstraint("review_id", "idempotency_key", name="uq_review_job_submission"),
    )
    op.create_index("idx_review_jobs_review", "review_jobs", ["review_id", "run_id"])
    op.execute("PRAGMA user_version = 8")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT count(*) FROM runs WHERE kind='review'")).scalar_one():
        raise RuntimeError("Restore the pre-review database backup to downgrade with review data.")
    op.drop_table("review_jobs")
    op.drop_table("review_revisions")
    op.drop_table("reviews")
    op.drop_index("idx_runs_kind_created", table_name="runs")
    op.drop_column("runs", "kind")
    op.execute("PRAGMA user_version = 7")
