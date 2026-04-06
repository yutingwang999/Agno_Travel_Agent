"""Shared pytest configuration.

Loads the project .env file before any test runs so that DATABASE_URL,
GEMINI_API_KEY, and other required variables are available to integration
tests without requiring the caller to export them manually.

Variables already set in the shell are NOT overridden (override=False).
"""

import os

from dotenv import load_dotenv

# Resolve .env relative to the project root (one level above tests/)
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_FILE, override=False)
