"""Focused tests for extraction validation, chunking, retries, and merging."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from liteparse_agentic_document_extraction import extraction
from liteparse_agentic_document_extraction.models import (
    LineEvidence,
    ParsedDocument,
    ParsedPage,
    ProcessingOptions,
)


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"value": {"type": ["string", "null"]}},
        "required": ["value"],
    }


def line(number: int = 1, text: str = "Invoice INV-1") -> LineEvidence:
    return LineEvidence(f"p1-l{number:04d}", 1, text, (1, 2, 30, 10), "ocr_300", 0.9)


def parsed(pages: tuple[ParsedPage, ...], lines: tuple[LineEvidence, ...]) -> ParsedDocument:
    return ParsedDocument("\n".join(p.markdown for p in pages), pages, lines, (), (), 1, (1,), ())


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ({"type": "object", "properties": [], "required": []}, "Invalid"),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"$ref": "#/$defs/x"}},
                "required": ["x"],
            },
            r"\$ref",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"type": "string"}},
                "required": [],
            },
            "require all",
        ),
    ],
)
def test_schema_rejects_unsupported_shapes(bad: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        extraction.validate_user_schema(bad)


def test_schema_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "MAX_SCHEMA_BYTES", 5)
    with pytest.raises(ValueError, match="100 KB"):
        extraction.validate_user_schema(schema())


def test_evidence_validation_covers_paths_quotes_and_statuses() -> None:
    catalog = (line(),)
    base = {"data": {"value": "INV-1"}, "issues": []}
    valid = {
        **base,
        "status": "complete",
        "evidence": [{"path": "/data/value", "line_ids": [catalog[0].id], "quote": "INV-1"}],
    }
    assert extraction.validate_extraction(valid, schema(), catalog)[0] == []

    cases = [
        {**valid, "evidence": [{"path": "bad", "line_ids": [catalog[0].id], "quote": "INV-1"}]},
        {**valid, "evidence": [{"path": "/data/value", "line_ids": ["bad"], "quote": "INV-1"}]},
        {
            **valid,
            "evidence": [{"path": "/data/value", "line_ids": [catalog[0].id], "quote": "nope"}],
        },
        {**valid, "evidence": [{"path": "/data", "line_ids": [catalog[0].id], "quote": "INV-1"}]},
        {
            **valid,
            "data": {"value": None},
            "evidence": [{"path": "/data/value", "line_ids": [catalog[0].id], "quote": "INV-1"}],
        },
        {**valid, "status": "complete", "issues": [{"code": "missing"}]},
        {**valid, "status": "partial"},
        {**valid, "status": "failed"},
    ]
    for candidate in cases:
        assert extraction.validate_extraction(candidate, schema(), catalog)[0]


def test_generic_metadata_does_not_require_evidence() -> None:
    data = {
        "document_type": None,
        "fields": [{"name": "id", "value": "INV-1", "value_type": "identifier"}],
    }
    result = {
        "status": "complete",
        "data": data,
        "evidence": [{"path": "/data/fields/0/value", "line_ids": [line().id], "quote": "INV-1"}],
        "issues": [],
    }
    assert (
        extraction.validate_extraction(
            result, extraction.generic_data_schema(), (line(),), generic_schema=True
        )[0]
        == []
    )


def test_chunking_preserves_oversized_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "MAX_CHUNK_CHARS", 20)
    no_lines = parsed((ParsedPage(1, "x" * 45, ()),), ())
    assert [len(chunk.markdown) for chunk in extraction._chunks(no_lines)] == [20, 20, 5]

    lines = (line(1, "a" * 15), line(2, "b" * 15))
    with_lines = parsed((ParsedPage(1, "large", tuple(item.id for item in lines)),), lines)
    assert len(extraction._chunks(with_lines)) == 2


def test_model_call_retries_then_returns_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            SimpleNamespace(output_text=""),
            SimpleNamespace(
                output_text=json.dumps(
                    {"status": "complete", "data": {"value": "INV-1"}, "evidence": [], "issues": []}
                )
            ),
        ]
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_kwargs: next(responses)))
    monkeypatch.setattr(extraction, "get_openai_client", lambda: client)
    result, hashes = extraction._model_call(
        kind="merge",
        payload="[]",
        lines=(line(),),
        options=ProcessingOptions("Do {{this}}"),
        data_schema=schema(),
    )
    assert result["status"] == "partial"
    assert result["issues"][-1]["message"].startswith("Local evidence")
    assert len(hashes) == 2


def test_extract_document_merges_and_handles_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = tuple(ParsedPage(i, f"page {i}", ()) for i in range(1, 4))
    document = parsed(pages, ())
    monkeypatch.setattr(extraction, "MAX_CHUNK_PAGES", 1)
    calls = 0

    def fake_call(**kwargs: Any) -> tuple[dict[str, Any], tuple[str, ...]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("chunk")
        if kwargs["kind"] == "merge":
            raise RuntimeError("merge")
        return {"status": "complete", "data": {"value": None}, "evidence": [], "issues": []}, ("h",)

    monkeypatch.setattr(extraction, "_model_call", fake_call)
    result = extraction.extract_document(document, ProcessingOptions("extract", schema=schema()))
    assert result.status == "partial"
    assert {issue.code for issue in result.issues} == {
        "extraction_chunk_failed",
        "extraction_merge_failed",
    }

    monkeypatch.setattr(
        extraction, "_model_call", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError())
    )
    failed = extraction.extract_document(document, ProcessingOptions("extract", schema=schema()))
    assert failed.status == "failed"
