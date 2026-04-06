"""Shared pytest configuration.

Loads the project .env file before any test runs so that DATABASE_URL,
GEMINI_API_KEY, and other required variables are available to integration
tests without requiring the caller to export them manually.

Variables already set in the shell are NOT overridden (override=False).
"""

import os
import sys

from dotenv import load_dotenv

# Resolve .env relative to the project root (one level above tests/)
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_FILE, override=False)

# Redirect Agno's ColoredRichHandler from stdout to stderr.
#
# Agno configures a Rich-based log handler that writes to sys.stdout by
# default.  Several tests parse structured SSE JSON from captured stdout
# (capsys.readouterr().out) and break when Agno's internal log_error()
# calls inject extra text into stdout (e.g. DB connection errors during
# the rag_retrieve step).  Redirecting to stderr keeps stdout clean.
try:
    from rich.console import Console

    from agno.utils.log import logger as _agno_logger

    for _handler in _agno_logger.handlers:
        if hasattr(_handler, "console"):
            _handler.console = Console(file=sys.stderr, highlight=False)
except Exception:
    pass
