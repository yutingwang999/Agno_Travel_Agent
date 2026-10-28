"""CAG matcher: semantic matching of user intent to itinerary categories.

CAG (Cache-Augmented Generation) approach: the full reference dataset is loaded
from the database into Python memory, then cosine similarity is computed
in-process using numpy — no pgvector query is issued for the match.

This is distinct from RAG, which retrieves dynamically.  Here the reference
data is *preloaded* into the matching context on every call.

Public API:
    match_category(intent_text, db_url, api_key, embedding_model) -> MatchResult
"""

from dataclasses import dataclass

import numpy as np
from google import genai
from google.genai import types
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.itinerary_category import ItineraryCategory

EMBEDDING_DIMENSIONS = 768
MINIMUM_SIMILARITY = 0.30    # scores below this trigger the fallback category
DEFAULT_CATEGORY_KEY = "family"  # used when no category meets the threshold


@dataclass
class MatchResult:
    """Result of a CAG category match."""

    category_key: str
    confidence_score: float
    tone: str
    constraints: str
    is_fallback: bool


def empty_fallback() -> MatchResult:
    """Return the default category with zero confidence.

    Used when there is nothing to match against (no rows, or no row has an
    embedding) and by the cag_match step when embedding or loading fails.
    """
    return MatchResult(
        category_key=DEFAULT_CATEGORY_KEY,
        confidence_score=0.0,
        tone="friendly and helpful",
        constraints="",
        is_fallback=True,
    )


def _compute_embedding(text: str, api_key: str, model: str) -> list[float]:
    """Return a 768-dimensional embedding for *text* via the Gemini API."""
    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model=f"models/{model}",
        contents=text,
        config=types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=EMBEDDING_DIMENSIONS,
        ),
    )
    return result.embeddings[0].values


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def match_category(
    intent_text: str,
    db_url: str,
    api_key: str,
    embedding_model: str = "gemini-embedding-001",
) -> MatchResult:
    """Find the closest itinerary category for *intent_text*.

    CAG approach: all rows from ``itinerary_categories`` are loaded into Python
    memory, then cosine similarity is computed in-process using numpy against
    the embedded query.  No pgvector similarity query is issued — the full
    reference dataset is preloaded into the matching context.

    Args:
        intent_text:     Free-text description of the user's travel intent.
        db_url:          SQLAlchemy-compatible PostgreSQL connection string.
        api_key:         Gemini API key.
        embedding_model: Gemini embedding model name — must match the model used
                         in ``scripts/seed.py`` so vectors are comparable.

    Returns:
        MatchResult with the matched category key, cosine similarity score,
        tone, constraints, and a flag indicating whether the fallback was used.
    """
    query_vector = _compute_embedding(intent_text, api_key, embedding_model)

    # CAG: preload the full reference dataset into Python memory.
    engine = create_engine(db_url)
    with Session(engine) as session:
        categories = list(session.scalars(select(ItineraryCategory)).all())

    if not categories:
        return empty_fallback()

    # Compute cosine similarity in-process against every loaded category.
    best_category: ItineraryCategory | None = None
    best_similarity: float = -1.0

    for category in categories:
        if category.embedding_vector is None:
            continue
        sim = _cosine_similarity(query_vector, category.embedding_vector)
        if sim > best_similarity:
            best_similarity = sim
            best_category = category

    if best_category is None:
        # All rows had null embeddings — return a generic fallback.
        return empty_fallback()

    if best_similarity < MINIMUM_SIMILARITY:
        # Best match is below the minimum acceptable threshold.
        # Use the default category but keep the raw score so downstream
        # steps (retrieval_decision) can still branch on confidence_score.
        fallback = next(
            (c for c in categories if c.category_key == DEFAULT_CATEGORY_KEY),
            best_category,
        )
        return MatchResult(
            category_key=fallback.category_key,
            confidence_score=best_similarity,
            tone=fallback.tone,
            constraints=fallback.constraints,
            is_fallback=True,
        )

    return MatchResult(
        category_key=best_category.category_key,
        confidence_score=best_similarity,
        tone=best_category.tone,
        constraints=best_category.constraints,
        is_fallback=False,
    )
