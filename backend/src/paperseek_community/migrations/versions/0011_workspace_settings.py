"""Saved model connections, data-source settings and workspace defaults.

Secrets are AES-GCM ciphertext under the Community master key; runs still
receive their own short-lived copies at submission time.
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_workspace_settings"
down_revision = "0010_record_titles"
branch_labels = None
depends_on = None


def _test_columns():
    return [
        sa.Column("test_status", sa.String(), nullable=False, server_default="untested"),
        sa.Column("test_latency_ms", sa.Integer()),
        sa.Column("test_code", sa.String(), nullable=False, server_default=""),
        sa.Column("tested_at", sa.String()),
    ]


def upgrade():
    op.create_table(
        "model_connections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("api_type", sa.String(), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary()),
        sa.Column("nonce", sa.LargeBinary()),
        *_test_columns(),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("idx_model_connections_kind", "model_connections", ["kind", "created_at"])
    op.create_table(
        "source_settings",
        sa.Column("source_id", sa.String(), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary()),
        sa.Column("nonce", sa.LargeBinary()),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="{}"),
        *_test_columns(),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "workspace_settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
    )
    op.execute("PRAGMA user_version = 11")


def downgrade():
    for table in ("model_connections", "source_settings", "workspace_settings"):
        if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("Restore a backup to downgrade without losing saved connections.")
    op.drop_table("workspace_settings")
    op.drop_table("source_settings")
    op.drop_index("idx_model_connections_kind", "model_connections")
    op.drop_table("model_connections")
    op.execute("PRAGMA user_version = 10")
