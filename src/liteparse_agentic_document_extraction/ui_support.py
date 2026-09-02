"""Pure helpers used by the Streamlit interface."""

from __future__ import annotations

import json
from typing import Any

from .settings import MAX_SCHEMA_BYTES


def read_schema(mode: str, pasted: str, uploaded: Any) -> dict[str, Any] | None:
    """Read and size-check the selected optional JSON Schema."""
    if mode == "None":
        return None
    raw = pasted.encode() if mode == "Paste" else uploaded.getvalue() if uploaded else b""
    if not raw.strip():
        raise ValueError("Selected schema mode requires JSON Schema content")
    if len(raw) > MAX_SCHEMA_BYTES:
        raise ValueError("JSON Schema exceeds 100 KB")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON Schema is not valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON Schema must be a JSON object")
    return parsed
