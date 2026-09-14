"""Tests for validation, extraction invariants, orchestration, and exports."""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from liteparse_agentic_document_extraction.extraction import (
    extract_document,
    extraction_schema,
    generic_data_schema,
    validate_extraction,
    validate_user_schema,
)
from liteparse_agentic_document_extraction.models import (
    DocumentArtifact,
    ExtractionResult,
    LineEvidence,
    ParsedDocument,
    ParsedPage,
    ProcessingOptions,
    RunStatus,
)
from liteparse_agentic_document_extraction.pipeline import (
    artifact_json,
    parse_target_pages,
    process_document,
    result_zip,
    safe_stem,
    validate_upload,
)
from liteparse_agentic_document_extraction.repair import Region, merge_regions, padded_crop


def png_bytes(width: int = 100, height: int = 100) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def strict_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"invoice_number": {"type": ["string", "null"]}},
        "required": ["invoice_number"],
    }


def parsed_document(page_count: int = 1, annotated_pdf: bytes = b"") -> ParsedDocument:
    lines = tuple(
        LineEvidence(
            f"p{page}-l0001",
            page,
            f"Invoice INV-{page}",
            (1, 2, 30, 10),
            "ocr_300",
            0.9,
        )
        for page in range(1, page_count + 1)
    )
    pages = tuple(
        ParsedPage(page, f"# Invoice\n\nINV-{page}", (f"p{page}-l0001",))
        for page in range(1, page_count + 1)
    )
    return ParsedDocument(
        markdown="\n\n".join(page.markdown for page in pages),
        pages=pages,
        lines=lines,
        repairs=(),
        issues=(),
        source_page_count=page_count,
        processed_pages=tuple(range(1, page_count + 1)),
        prompt_template_hashes=("a" * 64,),
        annotated_pdf=annotated_pdf,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("1", [1]), ("1-3,5", [1, 2, 3, 5])],
)
def test_parse_target_pages(value: str | None, expected: list[int] | None) -> None:
    assert parse_target_pages(value) == expected


@pytest.mark.parametrize("value", ["0", "2-1", "a", "1,,2", "1-101", "1-"])
def test_parse_target_pages_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_target_pages(value)


def test_upload_validation_and_safe_name() -> None:
    assert validate_upload("scan.PNG", png_bytes()) == ".png"
    assert validate_upload("doc.pdf", b"%PDF-1.7\nbody") == ".pdf"
    assert safe_stem("../../Invoice 123?.pdf") == "Invoice_123"
    assert safe_stem("CON.pdf") == "_CON"
    with pytest.raises(ValueError, match="Unsupported"):
        validate_upload("notes.txt", b"hello")
    with pytest.raises(ValueError, match="empty"):
        validate_upload("scan.png", b"")
    with pytest.raises(ValueError, match="not a PDF"):
        validate_upload("doc.pdf", b"not pdf")
    with pytest.raises(ValueError, match="invalid"):
        validate_upload("scan.png", b"not png")


def test_schema_validation_translates_errors() -> None:
    validate_user_schema(None)
    validate_user_schema(strict_schema())
    with pytest.raises(ValueError, match="root type"):
        validate_user_schema({"type": "array"})
    with pytest.raises(ValueError, match="additionalProperties"):
        validate_user_schema(
            {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        )
    with pytest.raises(ValueError, match="require all"):
        validate_user_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"type": "string"}},
                "required": [],
            }
        )
    with pytest.raises(ValueError, match=r"\$ref"):
        validate_user_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"$ref": "#/$defs/x"}},
                "required": ["x"],
            }
        )
    with pytest.raises(ValueError, match="Invalid JSON Schema"):
        validate_user_schema(
            {"type": "object", "additionalProperties": False, "properties": {}, "required": 1}
        )


def test_region_merge_and_crop() -> None:
    merged = merge_regions(
        [
            Region(1, (10, 10, 30, 30), "tiny"),
            Region(1, (31, 10, 50, 30), "blurred"),
            Region(1, (80, 80, 90, 90), "mark"),
        ],
        100,
        100,
    )
    assert [region.bbox for region in merged] == [(10, 10, 50, 30), (80, 80, 90, 90)]
    assert padded_crop((10, 20, 90, 80), 100, 100) == pytest.approx((0.18, 0.08, 0.18, 0.08))


def valid_result() -> dict[str, Any]:
    return {
        "status": "complete",
        "data": {"invoice_number": "INV-1"},
        "evidence": [{"path": "/data/invoice_number", "line_ids": ["p1-l0001"], "quote": "INV-1"}],
        "issues": [],
    }


def test_evidence_contract_rejects_false_grounding() -> None:
    catalog = parsed_document().lines
    errors, trusted = validate_extraction(valid_result(), strict_schema(), catalog)
    assert errors == []
    assert len(trusted) == 1

    two_fields = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a", "b"],
    }
    incomplete = {
        "status": "complete",
        "data": {"a": "INV-1", "b": "missing"},
        "evidence": [{"path": "/data/a", "line_ids": ["p1-l0001"], "quote": "INV-1"}],
        "issues": [],
    }
    assert any(
        "/data/b" in error for error in validate_extraction(incomplete, two_fields, catalog)[0]
    )

    wrong = valid_result()
    wrong["evidence"] = [{"path": "/status", "line_ids": ["p1-l0001"], "quote": ""}]
    errors, trusted = validate_extraction(wrong, strict_schema(), catalog)
    assert trusted == []
    assert any("unknown data pointer" in error for error in errors)

    contradictory = {"status": "complete", "data": None, "evidence": [], "issues": []}
    assert validate_extraction(contradictory, strict_schema(), catalog)[0]
    assert extraction_schema(generic_data_schema())["properties"]["evidence"]


class FakeResponses:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.outputs.pop(0)))


def test_extraction_retries_bad_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = valid_result()
    invalid["evidence"] = [
        {"path": "/data/invoice_number", "line_ids": ["missing"], "quote": "INV-1"}
    ]
    responses = FakeResponses([invalid, valid_result()])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.extraction.get_openai_client",
        lambda: SimpleNamespace(responses=responses),
    )
    result = extract_document(
        parsed_document(), ProcessingOptions("Extract invoice number", strict_schema())
    )
    assert result.status == "complete"
    assert len(responses.calls) == 2
    assert "unknown or empty line IDs" in responses.calls[1]["input"][1]["content"]
    assert responses.calls[0]["store"] is False


def test_chunk_merge_and_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_call(**kwargs: Any) -> tuple[dict[str, Any], tuple[str, ...]]:
        calls.append(kwargs["kind"])
        return valid_result(), ("f" * 64,)

    monkeypatch.setattr("liteparse_agentic_document_extraction.extraction._model_call", fake_call)
    result = extract_document(
        parsed_document(9), ProcessingOptions("Extract invoice number", strict_schema())
    )
    assert calls == ["extract", "extract", "merge"]
    assert result.status == "complete"

    count = 0

    def one_failure(**kwargs: Any) -> tuple[dict[str, Any], tuple[str, ...]]:
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError
        return valid_result(), ("f" * 64,)

    monkeypatch.setattr("liteparse_agentic_document_extraction.extraction._model_call", one_failure)
    result = extract_document(
        parsed_document(9), ProcessingOptions("Extract invoice number", strict_schema())
    )
    assert result.status == "partial"
    assert result.issues[0].code == "extraction_chunk_failed"


def test_process_document_preserves_markdown_on_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parsed_document()
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.parse_document", lambda *_: parsed
    )

    def fail(*_args: Any) -> None:
        raise RuntimeError("provider detail")

    monkeypatch.setattr("liteparse_agentic_document_extraction.pipeline.extract_document", fail)
    artifact = process_document(
        "invoice.png", png_bytes(), ProcessingOptions("Extract", extract_data=True)
    )
    assert artifact.status is RunStatus.PARTIAL
    assert artifact.markdown
    assert artifact.output["stages"]["extraction"] == "failed"
    assert artifact.output["data"] is None
    assert artifact.error is None


def test_process_document_complete_v22(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = parsed_document(annotated_pdf=b"%PDF-annotated")
    extraction = ExtractionResult(
        "complete",
        {"invoice_number": "INV-1"},
        tuple(valid_result()["evidence"]),
        (),
        ("b" * 64,),
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.parse_document", lambda *_: parsed
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.extract_document", lambda *_: extraction
    )
    artifact = process_document(
        "invoice.png", png_bytes(), ProcessingOptions("Extract", extract_data=True)
    )
    assert artifact.status is RunStatus.COMPLETE
    assert artifact.output["schema_version"] == "2.2"
    assert artifact.output["evidence"][0]["sources"][0]["bbox"] == [1, 2, 30, 10]
    assert artifact.output["document"]["processed_pages"] == [1]
    assert artifact.annotated_pdf == b"%PDF-annotated"


def test_process_document_skips_optional_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.parse_document",
        lambda *_: parsed_document(),
    )

    def unexpected_extraction(*_args: Any) -> None:
        raise AssertionError("extraction should be skipped")

    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.extract_document", unexpected_extraction
    )
    artifact = process_document(
        "invoice.png",
        png_bytes(),
        ProcessingOptions(schema={"invalid": "ignored"}),
    )

    assert artifact.status is RunStatus.COMPLETE
    assert artifact.output["schema_version"] == "2.2"
    assert artifact.output["stages"]["extraction"] == "skipped"
    assert artifact.output["stages"]["annotation"] == "skipped"
    assert artifact.output["data"] is None
    assert artifact.output["evidence"] == []


def test_process_document_input_failure() -> None:
    artifact = process_document("notes.txt", b"hello", ProcessingOptions("Extract"))
    assert artifact.status is RunStatus.FAILED
    assert artifact.error == "Unsupported file type: .txt"


def test_artifact_exports_use_unique_names() -> None:
    artifacts = [
        DocumentArtifact(
            "Invoice 1.pdf",
            b"pdf",
            str(index) * 64,
            status=RunStatus.COMPLETE,
            markdown=f"# {index}",
            output={"status": "complete"},
        )
        for index in range(1, 4)
    ]
    artifacts[0].annotated_pdf = b"%PDF-annotated"
    assert json.loads(artifact_json(artifacts[0]))["status"] == "complete"
    with zipfile.ZipFile(io.BytesIO(result_zip(artifacts))) as archive:
        assert archive.namelist() == [
            "Invoice_1.md",
            "Invoice_1.json",
            "Invoice_1.annotated.pdf",
            "Invoice_1-2.md",
            "Invoice_1-2.json",
            "Invoice_1-3.md",
            "Invoice_1-3.json",
        ]
