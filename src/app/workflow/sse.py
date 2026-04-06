"""SSE event builder utility.

Produces the structured event format defined in DESIGN.md section 9:
{
    "session_id": "...",
    "step": "cag_match",
    "status": "completed",
    "timestamp": "...",
    "data": {},
    "error": null
}
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def build_sse_event(
    session_id: str,
    step: str,
    status: str,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured SSE event dict."""
    return {
        "session_id": session_id,
        "step": step,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data if data is not None else {},
        "error": error,
    }


def sse_event_to_json(event: Dict[str, Any]) -> str:
    """Serialize an SSE event dict to a JSON string."""
    return json.dumps(event)
