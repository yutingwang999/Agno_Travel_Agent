"""Agno-compatible Gemini embedder wrapping google-generativeai.

Implements the :class:`agno.knowledge.embedder.base.Embedder` interface so that
Agno's :class:`agno.vectordb.pgvector.PgVector` can embed documents and queries
using the same Gemini model (gemini-embedding-001, 768 dimensions) that the seed
script uses, keeping similarity scores comparable.

Usage::

    from app.workflow.gemini_embedder import GeminiEmbedder

    embedder = GeminiEmbedder(api_key="...", model="gemini-embedding-001")
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import google.generativeai as genai
from agno.knowledge.embedder.base import Embedder

EMBEDDING_DIMENSIONS = 768
DEFAULT_MODEL = "gemini-embedding-001"


@dataclass
class GeminiEmbedder(Embedder):
    """Agno Embedder implementation backed by the Gemini embedding API.

    Attributes:
        model:      Gemini embedding model name.  Must match the model used in
                    ``scripts/seed.py`` so that cosine similarity scores are
                    comparable across insert and search.
        api_key:    Gemini API key.  Reads from the ``GEMINI_API_KEY``
                    environment variable when not supplied directly.
        dimensions: Output dimensionality — fixed at 768 for gemini-embedding-001.
    """

    model: str = DEFAULT_MODEL
    api_key: Optional[str] = None
    dimensions: int = EMBEDDING_DIMENSIONS

    def __post_init__(self) -> None:
        if self.api_key:
            genai.configure(api_key=self.api_key)

    def get_embedding(self, text: str) -> List[float]:
        """Return a 768-dimensional embedding for *text* via the Gemini API.

        Args:
            text: The text to embed.

        Returns:
            A list of 768 floats representing the embedding vector.
        """
        result = genai.embed_content(
            model=f"models/{self.model}",
            content=text,
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=self.dimensions,
        )
        return result["embedding"]

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Return embedding and usage info (usage is not exposed by Gemini API here).

        Args:
            text: The text to embed.

        Returns:
            Tuple of (embedding vector, None) — Gemini does not return token
            usage for embed_content calls.
        """
        return self.get_embedding(text), None

    async def async_get_embedding(self, text: str) -> List[float]:
        """Async wrapper that runs the synchronous Gemini call in a thread pool.

        Args:
            text: The text to embed.

        Returns:
            A list of 768 floats representing the embedding vector.
        """
        return await asyncio.to_thread(self.get_embedding, text)

    async def async_get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Async wrapper returning (embedding, None).

        Args:
            text: The text to embed.

        Returns:
            Tuple of (embedding vector, None).
        """
        embedding = await self.async_get_embedding(text)
        return embedding, None
