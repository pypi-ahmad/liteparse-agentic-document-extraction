"""Tests for UI input helpers and the packaged launcher."""

from __future__ import annotations

from io import BytesIO

import pytest

import liteparse_agentic_document_extraction
from liteparse_agentic_document_extraction import server
from liteparse_agentic_document_extraction.ui_support import build_page_range, read_schema


@pytest.mark.parametrize(
    ("scope", "start", "end", "expected"),
    [
        ("All", 1, 1, None),
        ("Range", 3, 3, "3"),
        ("Range", 2, 8, "2-8"),
    ],
)
def test_build_page_range(scope: str, start: int, end: int, expected: str | None) -> None:
    assert build_page_range(scope, start, end) == expected


def test_build_page_range_rejects_descending_range() -> None:
    with pytest.raises(ValueError, match="Start page"):
        build_page_range("Range", 8, 2)


@pytest.mark.parametrize(
    ("mode", "pasted", "uploaded", "expected"),
    [
        ("None", "", None, None),
        ("Paste", '{"type":"object"}', None, {"type": "object"}),
        ("Upload", "", BytesIO(b'{"type":"object"}'), {"type": "object"}),
    ],
)
def test_read_schema(mode: str, pasted: str, uploaded: object, expected: object) -> None:
    assert read_schema(mode, pasted, uploaded) == expected


@pytest.mark.parametrize(
    ("mode", "pasted", "uploaded", "message"),
    [
        ("Paste", "", None, "requires"),
        ("Paste", "not json", None, "UTF-8 JSON"),
        ("Paste", "[]", None, "JSON object"),
    ],
)
def test_read_schema_rejects_bad_input(
    mode: str, pasted: str, uploaded: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        read_schema(mode, pasted, uploaded)


def test_read_schema_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("liteparse_agentic_document_extraction.ui_support.MAX_SCHEMA_BYTES", 2)
    with pytest.raises(ValueError, match="100 KB"):
        read_schema("Paste", "{} ", None)


def test_server_runs_packaged_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeApp:
        def run(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(server, "app", FakeApp())
    server.main()
    assert calls[0]["config"] == {"server.address": "127.0.0.1", "server.port": 9578}


def test_console_entrypoint_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(server, "main", lambda: called.append(True))
    liteparse_agentic_document_extraction.main()
    assert called == [True]
