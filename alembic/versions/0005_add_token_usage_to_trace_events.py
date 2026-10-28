"""Add LLM token usage columns to trace_events

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: steps without an LLM call, and providers that report no usage,
    # leave them empty.
    op.add_column("trace_events", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("trace_events", sa.Column("output_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("trace_events", "output_tokens")
    op.drop_column("trace_events", "input_tokens")
