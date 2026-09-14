"""Pure helpers used by the Streamlit interface.

Split out from ui.py so this logic can be unit tested directly without
Streamlit's AppTest harness.
"""

from __future__ import annotations

import json
from typing import Any

from .settings import MAX_SCHEMA_BYTES


def build_page_range(scope: str, start_page: int, end_page: int) -> str | None:
    """Convert UI page controls to LiteParse's inclusive range syntax."""
    if scope == "All":
        return None
    if start_page > end_page:
        raise ValueError("Start page cannot be greater than end page")
    return str(start_page) if start_page == end_page else f"{start_page}-{end_page}"


def read_schema(mode: str, pasted: str, uploaded: Any) -> dict[str, Any] | None:
    """Read and size-check the selected optional JSON Schema."""
    if mode == "None":
        return None
    # "Paste" mode always uses the text area; any other mode (Upload) reads
    # the uploaded file if present, else empty bytes to hit the check below.
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
