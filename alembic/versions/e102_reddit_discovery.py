"""Durable domain discovery, independent of the expiring offer snapshot."""
from alembic import op
import sqlalchemy as sa
revision = "e102_discovery"
down_revision = "d2610dba96ff"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("discovery_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("baseline", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False))
    op.create_index("ix_discovery_runs_source", "discovery_runs", ["source"])
    op.create_table("discovery_observations",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("baseline", sa.Boolean(), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False))
    op.create_index("ix_discovery_observations_source", "discovery_observations", ["source"])

def downgrade():
    raise RuntimeError("Discovery evidence is retained; restore a verified backup for rollback")
