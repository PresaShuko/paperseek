"""Display names never rewrite the submitted question or review topic."""

from alembic import op
import sqlalchemy as sa

revision = "0010_record_titles"
down_revision = "0009_bibliometrics"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("runs", "reviews"):
        op.add_column(
            table,
            sa.Column("display_title", sa.Text(), nullable=False, server_default=""),
        )
    op.execute("PRAGMA user_version = 10")


def downgrade():
    for table in ("runs", "reviews"):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT count(*) FROM {table} WHERE display_title <> ''"))
            .scalar_one()
        ):
            raise RuntimeError(
                "Restore a backup to downgrade without losing display titles."
            )
    for table in ("runs", "reviews"):
        op.drop_column(table, "display_title")
    op.execute("PRAGMA user_version = 9")
