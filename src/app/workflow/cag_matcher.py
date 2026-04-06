"""CAG matcher: semantic matching of user intent to itinerary categories.

Embeds the user's free-text intent using the Gemini embedding API and performs
a cosine similarity search against ``itinerary_categories.embedding_vector``
using pgvector.

The same embedding model and dimensionality (768) as the seed script are used
so that similarity scores are comparable.

Public API:
    match_category(intent_text, db_url, api_key, embedding_model) -> MatchResult
"""

from dataclasses import dataclass

import google.generativeai as genai
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


def match_category(
    intent_text: str,
    db_url: str,
    api_key: str,
    embedding_model: str = "gemini-embedding-001",
) -> MatchResult:
    """Find the closest itinerary category for *intent_text*.

    Embeds *intent_text*, queries ``itinerary_categories`` by cosine similarity,
    and returns the best match.  Falls back to ``DEFAULT_CATEGORY_KEY`` when no
    category exceeds ``MINIMUM_SIMILARITY``.

    Args:
        intent_text:     Free-text description of the user's travel intent.
        db_url:          SQLAlchemy-compatible PostgreSQL connection string.
        api_key:         Gemini API key.
        embedding_model: Gemini embedding model name — must match the model used
                         in ``scripts/seed.py`` so similarity scores are valid.

    Returns:
        MatchResult with the matched category key, cosine similarity score,
        tone, constraints, and a flag indicating whether the fallback was used.
    """
    query_vector = _compute_embedding(intent_text, api_key, embedding_model)

    engine = create_engine(db_url)
    with Session(engine) as session:
        # Order by cosine distance ascending so the closest category comes first.
        row = session.execute(
            select(
                ItineraryCategory,
                (
                    1 - ItineraryCategory.embedding_vector.cosine_distance(query_vector)
                ).label("similarity"),
            )
            .order_by(ItineraryCategory.embedding_vector.cosine_distance(query_vector))
            .limit(1)
        ).first()

        if row is None:
            # No categories exist in the database — return a generic fallback.
            return MatchResult(
                category_key=DEFAULT_CATEGORY_KEY,
                confidence_score=0.0,
                tone="friendly and helpful",
                constraints="",
                is_fallback=True,
            )

        best_category, best_similarity = row
        best_similarity = float(best_similarity)

        if best_similarity < MINIMUM_SIMILARITY:
            # Best match is below the minimum acceptable threshold.
            # Use the default category but keep the raw score so downstream
            # steps (retrieval_decision) can still branch on confidence_score.
            fallback = session.scalar(
                select(ItineraryCategory).where(
                    ItineraryCategory.category_key == DEFAULT_CATEGORY_KEY
                )
            )
            if fallback is None:
                # DEFAULT_CATEGORY_KEY not seeded — use the closest match anyway.
                fallback = best_category

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
