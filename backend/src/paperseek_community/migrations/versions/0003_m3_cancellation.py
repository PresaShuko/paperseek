"""Add the durable cancellation request timestamp for M3.

Revision ID: 0003_m3_cancellation
Revises: 0002_m3_artifacts
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_m3_cancellation"
down_revision = "0002_m3_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("cancel_requested_at", sa.String(), nullable=True))
    op.execute("PRAGMA user_version = 3")


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("cancel_requested_at")
    op.execute("PRAGMA user_version = 2")
