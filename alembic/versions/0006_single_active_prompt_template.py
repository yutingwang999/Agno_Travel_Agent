"""Allow at most one active prompt template version per key

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_prompt_templates_one_active"


def upgrade() -> None:
    # A database seeded before this migration can have several active versions of
    # one key; keep only the highest (ties broken by id) so the index can be built.
    op.execute(
        """
        UPDATE prompt_templates AS p
        SET is_active = false
        WHERE p.is_active
          AND EXISTS (
              SELECT 1 FROM prompt_templates AS q
              WHERE q.template_key = p.template_key
                AND q.is_active
                AND (q.version > p.version OR (q.version = p.version AND q.id > p.id))
          )
        """
    )
    op.create_index(
        INDEX_NAME,
        "prompt_templates",
        ["template_key"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    # The active flags cleared by upgrade() are not restored: which rows were
    # active before cannot be known, and several active versions was the bug.
    op.drop_index(INDEX_NAME, table_name="prompt_templates")
