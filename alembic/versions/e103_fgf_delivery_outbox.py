"""Prospective, durable FreeGameFindings community-lead delivery intents."""

import sqlalchemy as sa

from alembic import op

revision = "e103_fgf_delivery"
down_revision = "e102_discovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discovery_delivery_outbox",
        sa.Column("observation_key", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("classification_policy", sa.String(), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("permalink", sa.String(), nullable=False),
        sa.Column("code_revision", sa.String(), nullable=False),
        sa.Column("raw_sha256", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_discovery_delivery_outbox_status_created_at",
        "discovery_delivery_outbox",
        ["status", "created_at"],
    )
    op.create_index("ix_discovery_delivery_outbox_source", "discovery_delivery_outbox", ["source"])


def downgrade():
    raise RuntimeError("Delivery evidence is retained; restore a verified backup for rollback")
