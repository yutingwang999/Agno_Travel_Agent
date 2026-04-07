"""Enable pgvector extension and create itinerary_categories table

Revision ID: 0001
Revises:
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "itinerary_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category_key", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tone", sa.String(length=100), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False),
        sa.Column("embedding_vector", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_key"),
    )


def downgrade() -> None:
    op.drop_table("itinerary_categories")
    op.execute("DROP EXTENSION IF EXISTS vector CASCADE")
