"""Retrieval service: knowledge-base search via Agno's Knowledge + PgVector.

Uses Agno's :class:`~agno.knowledge.knowledge.Knowledge` class backed by
:class:`~agno.vectordb.pgvector.PgVector` and the project's Gemini embedder
to retrieve the top-k most relevant source document chunks for a travel query.

The same Gemini model and dimensionality (768) as the seed script are used so
that cosine similarity scores are comparable.

Public API::

    from app.workflow.retrieval_service import RetrievedChunk, retrieve_documents

    chunks = retrieve_documents(
        query_text="family activities in Sydney",
        db_url="postgresql://...",
        api_key="...",
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from agno.knowledge.knowledge import Knowledge

from app.workflow.knowledge_base import build_knowledge

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5


@dataclass
class RetrievedChunk:
    """A single retrieved source document chunk."""

    destination: str
    title: str
    chunk_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def retrieve_documents(
    query_text: str,
    db_url: str,
    api_key: str,
    embedding_model: str = "gemini-embedding-001",
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Retrieve the top-k most relevant source document chunks for *query_text*.

    Delegates to Agno's :class:`Knowledge` class, which embeds *query_text*
    with the Gemini API and performs a vector similarity search against the
    ``travel_docs`` table managed by :class:`~agno.vectordb.pgvector.PgVector`.

    On any exception (embedding failure, DB error, etc.) the error is logged
    and an empty list is returned so the workflow can continue without context.
    Agno's ``Knowledge.search()`` also handles its own internal errors
    gracefully, returning an empty list on failure.

    Args:
        query_text:      Free-text description of what the user is looking for.
        db_url:          SQLAlchemy-compatible PostgreSQL connection string.
        api_key:         Gemini API key.
        embedding_model: Gemini embedding model name — must match the model used
                         in ``scripts/seed.py`` so similarity scores are valid.
        top_k:           Maximum number of chunks to return (default 5).

    Returns:
        A list of :class:`RetrievedChunk` instances ordered by relevance
        (most similar first).  Empty list on failure or when no documents exist.
    """
    try:
        knowledge = build_knowledge(
            db_url=db_url,
            api_key=api_key,
            embedding_model=embedding_model,
        )
        return _search_knowledge(knowledge, query_text, top_k)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "rag_retrieve: failed to retrieve documents — continuing with empty context. "
            "Error: %s",
            exc,
        )
        return []


def _search_knowledge(
    knowledge: Knowledge,
    query_text: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """Execute the knowledge search and map Agno Documents to RetrievedChunk objects.

    Args:
        knowledge:  Configured Agno Knowledge instance.
        query_text: Free-text query.
        top_k:      Maximum number of results.

    Returns:
        List of :class:`RetrievedChunk` objects.
    """
    docs = knowledge.search(query=query_text, max_results=top_k)

    return [
        RetrievedChunk(
            destination=doc.meta_data.get("destination", ""),
            title=doc.name or "",
            chunk_text=doc.content,
            metadata=dict(doc.meta_data),
        )
        for doc in docs
    ]
