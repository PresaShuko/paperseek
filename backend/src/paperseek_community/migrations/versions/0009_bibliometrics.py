"""Saved bibliometric snapshots; source_run_id is provenance, not a cascade."""

from alembic import op
import sqlalchemy as sa

revision = "0009_bibliometrics"
down_revision = "0008_abstract_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bibliometric_analyses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_run_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("paper_count", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("deleted_at", sa.String()),
    )
    op.create_index(
        "idx_bibliometrics_created", "bibliometric_analyses", ["created_at", "id"]
    )
    op.execute("PRAGMA user_version = 9")


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM bibliometric_analyses"))
        .scalar_one()
    ):
        raise RuntimeError(
            "Restore the pre-bibliometrics backup to downgrade with analysis data."
        )
    op.drop_table("bibliometric_analyses")
    op.execute("PRAGMA user_version = 8")
