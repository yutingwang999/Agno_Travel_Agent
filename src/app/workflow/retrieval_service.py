"""Retrieval service: pgvector similarity search on source_documents.

Embeds the user's travel query using the Gemini embedding API and performs
a cosine similarity search against ``source_documents.embedding_vector``
using pgvector.

The same embedding model and dimensionality (768) as the seed script are used
so that similarity scores are comparable.

Public API:
    retrieve_documents(query_text, db_url, api_key, embedding_model, top_k) -> list[RetrievedChunk]
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import google.generativeai as genai
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.source_document import SourceDocument

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 768
DEFAULT_TOP_K = 5


@dataclass
class RetrievedChunk:
    """A single retrieved source document chunk."""

    destination: str
    title: str
    chunk_text: str
    similarity: float
    metadata_json: dict[str, Any] = field(default_factory=dict)


def _compute_embedding(text: str, api_key: str, model: str) -> list[float]:
    """Return a 768-dimensional embedding for *text* via the Gemini API."""
    genai.configure(api_key=api_key)
    result = genai.embed_content(
        model=f"models/{model}",
        content=text,
        task_type="SEMANTIC_SIMILARITY",
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    return result["embedding"]


def retrieve_documents(
    query_text: str,
    db_url: str,
    api_key: str,
    embedding_model: str = "gemini-embedding-001",
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Retrieve the top-k most relevant source document chunks for *query_text*.

    Embeds *query_text* with the Gemini API, then queries ``source_documents``
    ordered by cosine distance ascending (closest first).  Returns at most
    *top_k* results, or fewer when fewer documents exist.

    On any exception (embedding failure, DB error, etc.) the error is logged
    and an empty list is returned so the workflow can continue without context.

    Args:
        query_text:      Free-text description of what the user is looking for.
        db_url:          SQLAlchemy-compatible PostgreSQL connection string.
        api_key:         Gemini API key.
        embedding_model: Gemini embedding model name — must match the model used
                         in ``scripts/seed.py`` so similarity scores are valid.
        top_k:           Maximum number of chunks to return (default 5).

    Returns:
        A list of :class:`RetrievedChunk` instances, ordered by relevance
        (most similar first).  Empty list on failure or when no documents exist.
    """
    try:
        query_vector = _compute_embedding(query_text, api_key, embedding_model)
        return _query_source_documents(query_vector, db_url, top_k)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "rag_retrieve: failed to retrieve documents — continuing with empty context. "
            "Error: %s",
            exc,
        )
        return []


def _query_source_documents(
    query_vector: list[float],
    db_url: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """Execute the pgvector cosine similarity search against source_documents.

    Args:
        query_vector: The 768-dimensional query embedding.
        db_url:       SQLAlchemy-compatible PostgreSQL connection string.
        top_k:        Maximum number of rows to return.

    Returns:
        List of :class:`RetrievedChunk` ordered by cosine similarity descending.
    """
    engine = create_engine(db_url)
    with Session(engine) as session:
        rows = session.execute(
            select(
                SourceDocument,
                (
                    1 - SourceDocument.embedding_vector.cosine_distance(query_vector)
                ).label("similarity"),
            )
            .order_by(SourceDocument.embedding_vector.cosine_distance(query_vector))
            .limit(top_k)
        ).all()

    return [
        RetrievedChunk(
            destination=row.SourceDocument.destination,
            title=row.SourceDocument.title,
            chunk_text=row.SourceDocument.chunk_text,
            similarity=float(row.similarity),
            metadata_json=row.SourceDocument.metadata_json or {},
        )
        for row in rows
    ]
