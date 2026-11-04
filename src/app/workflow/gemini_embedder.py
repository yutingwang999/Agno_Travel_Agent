"""Agno-compatible Gemini embedder wrapping google-genai.

Implements the :class:`agno.knowledge.embedder.base.Embedder` interface so that
Agno's :class:`agno.vectordb.pgvector.PgVector` can embed documents and queries
using the same Gemini model (gemini-embedding-001, 768 dimensions) that the seed
script uses, keeping similarity scores comparable.

Usage::

    from app.workflow.gemini_embedder import GeminiEmbedder

    embedder = GeminiEmbedder(api_key="...", model="gemini-embedding-001")
"""

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from agno.knowledge.embedder.base import Embedder

EMBEDDING_DIMENSIONS = 768
DEFAULT_MODEL = "gemini-embedding-001"

TASK_TYPE_QUERY = "RETRIEVAL_QUERY"
TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_TYPE_SEMANTIC = "SEMANTIC_SIMILARITY"


@dataclass
class GeminiEmbedder(Embedder):
    """Agno Embedder implementation backed by the Gemini embedding API.

    Agno's PgVector calls ``get_embedding`` for a search query and
    ``get_embedding_and_usage`` for a document, so those two paths carry the
    query and the document task type.

    Attributes:
        model:      Gemini embedding model name.  Must match the model used in
                    ``scripts/seed.py`` so that cosine similarity scores are
                    comparable across insert and search.
        api_key:    Gemini API key.  Reads from the ``GEMINI_API_KEY``
                    environment variable when not supplied directly.
        dimensions: Output dimensionality — fixed at 768 for gemini-embedding-001.
        query_task_type:    Gemini task type for search queries.
        document_task_type: Gemini task type for documents.
        cache_dir:  When set, document embeddings are cached here by text, model
                    and task type, so re-seeding does not repeat paid API calls.
                    Search queries are never cached.
    """

    model: str = DEFAULT_MODEL
    api_key: Optional[str] = None
    dimensions: int = EMBEDDING_DIMENSIONS
    query_task_type: str = TASK_TYPE_QUERY
    document_task_type: str = TASK_TYPE_DOCUMENT
    cache_dir: Optional[Path] = None

    def __post_init__(self) -> None:
        self._client = genai.Client(api_key=self.api_key)

    def _embed(self, text: str, task_type: str) -> List[float]:
        result = self._client.models.embed_content(
            model=f"models/{self.model}",
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self.dimensions,
            ),
        )
        return result.embeddings[0].values

    def _cache_path(self, text: str) -> Path:
        key = f"{self.model}\0{self.document_task_type}\0{self.dimensions}\0{text}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return Path(self.cache_dir) / digest[:2] / f"{digest}.json"

    def _embed_document(self, text: str) -> List[float]:
        if self.cache_dir is None:
            return self._embed(text, self.document_task_type)

        path = self._cache_path(text)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        embedding = self._embed(text, self.document_task_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written to a unique file, then moved: a concurrent or interrupted seed
        # never leaves a partial entry behind.
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(embedding), encoding="utf-8")
        os.replace(temporary, path)
        return embedding

    def get_embedding(self, text: str) -> List[float]:
        """Return a 768-dimensional embedding for a search query via the Gemini API.

        Args:
            text: The text to embed.

        Returns:
            A list of 768 floats representing the embedding vector.
        """
        return self._embed(text, self.query_task_type)

    def get_embedding_and_usage(self, text: str) -> Tuple[List[float], Optional[Dict]]:
        """Return a document's embedding and usage info (usage is not exposed by Gemini API here).

        Args:
            text: The text to embed.

        Returns:
            Tuple of (embedding vector, None) — Gemini does not return token
            usage for embed_content calls.
        """
        return self._embed_document(text), None

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
        return await asyncio.to_thread(self.get_embedding_and_usage, text)
