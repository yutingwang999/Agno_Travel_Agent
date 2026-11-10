"""Drop the unused source_documents table

The knowledge base lives in the Agno-managed tables of the ai schema; nothing has
ever read or written this table. Downgrade recreates it empty.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    op.drop_table("source_documents")


def downgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("destination", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding_vector", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
