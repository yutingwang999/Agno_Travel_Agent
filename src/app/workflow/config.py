"""Shared workflow configuration constants."""

# Minimum CAG confidence score to skip RAG retrieval.
# Raise to require retrieval more often; lower to rely more on cached answers.
RETRIEVAL_CONFIDENCE_THRESHOLD: float = 0.85
