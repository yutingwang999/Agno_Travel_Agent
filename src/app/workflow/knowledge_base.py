"""Knowledge base factory for the RAG retrieval step.

Builds an Agno :class:`~agno.knowledge.knowledge.Knowledge` instance backed by
:class:`~agno.vectordb.pgvector.PgVector` and the project's Gemini embedder.

Agno's PgVector manages its own table (``travel_docs`` in the ``ai`` schema)
and handles schema creation automatically, so no Alembic migration is needed
for the knowledge-base table.

The table name can be overridden with the ``KNOWLEDGE_TABLE_NAME`` environment
variable; the evaluation database keeps one table per corpus version
(``travel_docs_v1``, ...) and each evaluation run selects one this way.

Public API::

    from app.workflow.knowledge_base import build_knowledge

    knowledge = build_knowledge(db_url="postgresql://...", api_key="...", model="gemini-embedding-001")
    docs = knowledge.search("family activities in Sydney", max_results=5)
"""

import os
from pathlib import Path

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

from app.workflow.gemini_embedder import (
    TASK_TYPE_DOCUMENT,
    TASK_TYPE_QUERY,
    TASK_TYPE_SEMANTIC,
    GeminiEmbedder,
)

DEFAULT_KNOWLEDGE_TABLE_NAME = "travel_docs"

# (query task type, document task type). A table is searched with the profile it
# was embedded with: the corpus v1 tables keep "semantic" so the v0.1.0 baseline
# can be re-run.
TASK_TYPE_PROFILES = {
    "retrieval": (TASK_TYPE_QUERY, TASK_TYPE_DOCUMENT),
    "semantic": (TASK_TYPE_SEMANTIC, TASK_TYPE_SEMANTIC),
}
DEFAULT_TASK_TYPE_PROFILE = "retrieval"


def knowledge_table_name() -> str:
    """Return ``KNOWLEDGE_TABLE_NAME`` if set and non-empty, else ``travel_docs``."""
    return os.environ.get("KNOWLEDGE_TABLE_NAME") or DEFAULT_KNOWLEDGE_TABLE_NAME


def knowledge_task_types() -> tuple[str, str]:
    """Return the (query, document) task types selected by ``KNOWLEDGE_TASK_TYPES``."""
    profile = os.environ.get("KNOWLEDGE_TASK_TYPES") or DEFAULT_TASK_TYPE_PROFILE
    if profile not in TASK_TYPE_PROFILES:
        raise ValueError(f"KNOWLEDGE_TASK_TYPES must be one of {sorted(TASK_TYPE_PROFILES)}, got {profile!r}")
    return TASK_TYPE_PROFILES[profile]


def build_knowledge(
    db_url: str,
    api_key: str,
    embedding_model: str = "gemini-embedding-001",
    table_name: str | None = None,
    cache_dir: Path | None = None,
) -> Knowledge:
    """Construct the Agno Knowledge instance for the travel RAG knowledge base.

    Creates (or reuses) the knowledge-base table in the ``ai`` schema via
    Agno's PgVector auto-schema creation.  The same Gemini model and
    dimensionality (768) are used here as in ``scripts/seed.py`` so that
    cosine similarity scores are comparable.

    Args:
        db_url:          SQLAlchemy-compatible PostgreSQL connection string.
        api_key:         Gemini API key used by the embedder.
        embedding_model: Gemini embedding model name.
        table_name:      Table in the ``ai`` schema; defaults to
                         :func:`knowledge_table_name`.
        cache_dir:       Where to cache document embeddings; seeding sets it.

    Returns:
        A configured :class:`Knowledge` instance ready for insert and search.
    """
    query_task_type, document_task_type = knowledge_task_types()
    embedder = GeminiEmbedder(
        api_key=api_key,
        model=embedding_model,
        query_task_type=query_task_type,
        document_task_type=document_task_type,
        cache_dir=cache_dir,
    )

    vector_db = PgVector(
        table_name=table_name or knowledge_table_name(),
        db_url=db_url,
        search_type=SearchType.vector,
        embedder=embedder,
        distance="cosine",
    )

    return Knowledge(vector_db=vector_db)
