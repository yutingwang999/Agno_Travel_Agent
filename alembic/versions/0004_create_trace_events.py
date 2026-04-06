"""Create trace_events table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trace_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("step_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("prompt_template_key", sa.String(length=100), nullable=True),
        sa.Column("prompt_template_version", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=200), nullable=True),
        sa.Column("degraded_mode", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trace_events_session_id", "trace_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_trace_events_session_id", table_name="trace_events")
    op.drop_table("trace_events")
