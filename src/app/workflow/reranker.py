"""Cross-Encoder reranking of retrieval candidates (rebuild-rag step d).

The model and its heavy imports load on first use and stay for the life of the
process. If loading or scoring fails, the candidates keep their order, so retrieval
still answers (spec: Reranking failure fallback).

RERANK_MODEL selects the model and RERANK_DEVICE where it runs. The device defaults
to the CPU, because a deployment is unlikely to have a GPU and the latency limit is
measured there.
"""

import logging
import os
from functools import lru_cache

from agno.knowledge.document.base import Document

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_RERANK_DEVICE = "cpu"


@lru_cache(maxsize=1)
def _load_model(model_name: str, device: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device=device)


def rerank(query: str, documents: list[Document], top_k: int) -> list[Document]:
    """Return the ``top_k`` documents the Cross-Encoder scores highest, best first.

    Equal scores keep the candidates' order. On any failure the first ``top_k``
    candidates are returned in their original order.
    """
    if not documents:
        return []
    try:
        model = _load_model(
            os.environ.get("RERANK_MODEL") or DEFAULT_RERANK_MODEL,
            os.environ.get("RERANK_DEVICE") or DEFAULT_RERANK_DEVICE,
        )
        scores = model.predict([(query, document.content) for document in documents])
        order = sorted(range(len(documents)), key=lambda position: (-float(scores[position]), position))
    except Exception as exc:  # noqa: BLE001
        logger.error("rerank: failed, keeping the order before reranking. Error: %s", exc)
        return documents[:top_k]
    return [documents[position] for position in order[:top_k]]
