"""Hybrid retrieval: BM25 keyword search and vector search, fused with reciprocal rank fusion.

Agno's own hybrid search uses Postgres full-text ranking and a weighted score, so
BM25 + RRF lives here; the evaluation compares the two (rebuild-rag task 4.3).

The BM25 index is built in memory on first use for a destination and kept for the life
of the process, so a server must be restarted after the knowledge base is re-seeded.
"""

import re
from functools import lru_cache

from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from rank_bm25 import BM25Okapi
from sqlalchemy import create_engine, text

AUSTRALIA_WIDE = "australia"
CANDIDATES_PER_SEARCH = 20
# The usual constant of reciprocal rank fusion: it damps the difference between top ranks.
RRF_K = 60

_TOKEN = re.compile(r"\w+")


def _tokenize(value: str) -> list[str]:
    return _TOKEN.findall(value.lower())


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    """Merge rankings of ids, best first: each id scores 1 / (k + rank) in every ranking it is in.

    Only ranks count, because BM25 scores and vector distances are not comparable.
    Ties keep the order in which the ids were first seen.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: -scores[item])


def _load_documents(db_url: str, table_name: str, destination: str | None) -> list[Document]:
    query = f'SELECT name, content, meta_data FROM ai."{table_name}"'
    params = {}
    if destination:
        query += " WHERE meta_data->>'destination' IN (:destination, :australia)"
        params = {"destination": destination, "australia": AUSTRALIA_WIDE}
    # Ordered so that equal BM25 scores always rank the same way.
    query += " ORDER BY meta_data->>'chunk_id'"
    with create_engine(db_url).connect() as connection:
        rows = connection.execute(text(query), params).all()
    return [Document(name=row.name, content=row.content, meta_data=row.meta_data) for row in rows]


@lru_cache(maxsize=64)
def _keyword_index(db_url: str, table_name: str, destination: str | None) -> tuple[list[Document], BM25Okapi | None]:
    documents = _load_documents(db_url, table_name, destination)
    if not documents:
        return documents, None
    return documents, BM25Okapi([_tokenize(document.content) for document in documents])


def keyword_search(
    query: str, db_url: str, table_name: str, destination: str | None, limit: int = CANDIDATES_PER_SEARCH
) -> list[Document]:
    """The documents BM25 ranks highest; a document sharing no term with the query is left out."""
    documents, index = _keyword_index(db_url, table_name, destination)
    if index is None:
        return []
    tokens = _tokenize(query)
    scores = index.get_scores(tokens)
    terms = set(tokens)
    matching = [
        (score, position)
        for position, score in enumerate(scores)
        if terms & set(_tokenize(documents[position].content))
    ]
    matching.sort(key=lambda item: (-item[0], item[1]))
    return [documents[position] for _, position in matching[:limit]]


def fused_candidates(
    knowledge: Knowledge, query: str, filters: list | None, destination: str | None
) -> list[Document]:
    """The top candidates of vector search and BM25, without duplicates, in RRF order."""
    vector_db = knowledge.vector_db
    vector = knowledge.search(query=query, max_results=CANDIDATES_PER_SEARCH, filters=filters)
    keyword = keyword_search(query, vector_db.db_url, vector_db.table_name, destination)

    by_id = {document.meta_data["chunk_id"]: document for document in [*keyword, *vector]}
    fused = reciprocal_rank_fusion(
        [[document.meta_data["chunk_id"] for document in ranking] for ranking in (vector, keyword)]
    )
    return [by_id[chunk_id] for chunk_id in fused]


def hybrid_search(
    knowledge: Knowledge, query: str, top_k: int, filters: list | None, destination: str | None
) -> list[Document]:
    """Fuse the top candidates of vector search and BM25, and return the best ``top_k``."""
    return fused_candidates(knowledge, query, filters, destination)[:top_k]
