"""Tests for validation, geometry, extraction, and exports."""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from PIL import Image

from liteparse_agentic_document_extraction.models import (
    DocumentArtifact,
    LineEvidence,
    ProcessingOptions,
    RunStatus,
)
from liteparse_agentic_document_extraction.pipeline import (
    Region,
    _catalog_prompt,
    _hard_regions,
    _line_catalog,
    _resolve_pointer,
    artifact_json,
    extract_data,
    merge_regions,
    padded_crop,
    parse_target_pages,
    process_document,
    result_zip,
    safe_stem,
    validate_upload,
    validate_user_schema,
)


def png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Create a valid in-memory PNG."""
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


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
    with pytest.raises(ValueError, match="Unsupported"):
        validate_upload("notes.txt", b"hello")
    with pytest.raises(ValueError, match="empty"):
        validate_upload("scan.png", b"")
    with pytest.raises(ValueError, match="not a PDF"):
        validate_upload("doc.pdf", b"not pdf")
    with pytest.raises(ValueError, match="invalid"):
        validate_upload("scan.png", b"not png")


def strict_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"invoice_number": {"type": ["string", "null"]}},
        "required": ["invoice_number"],
    }


def test_schema_validation() -> None:
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


def test_region_merge_and_crop() -> None:
    regions = [
        Region(1, (10, 10, 30, 30), "tiny"),
        Region(1, (31, 10, 50, 30), "blurred"),
        Region(1, (80, 80, 90, 90), "mark"),
    ]
    merged = merge_regions(regions, 100, 100)
    assert len(merged) == 2
    assert merged[0].bbox == (10, 10, 50, 30)
    assert padded_crop((10, 20, 90, 80), 100, 100) == pytest.approx((0.18, 0.08, 0.18, 0.08))

    many = [Region(1, (index * 20, 0, index * 20 + 5, 5), str(index)) for index in range(9)]
    assert len(merge_regions(many, 1000, 100)) == 8


def test_pointer_resolution() -> None:
    value = {"data": {"items": [{"name": "A/B"}]}}
    assert _resolve_pointer(value, "/data/items/0/name") == "A/B"
    with pytest.raises(KeyError):
        _resolve_pointer(value, "data/items")


class FakeResponses:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.outputs.pop(0)))


def test_extraction_validates_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = {
        "status": "complete",
        "data": {"invoice_number": "INV-7"},
        "evidence": [{"path": "/data/invoice_number", "line_ids": ["missing"], "quote": "INV-7"}],
        "issues": [],
    }
    valid = {
        "status": "complete",
        "data": {"invoice_number": "INV-7"},
        "evidence": [{"path": "/data/invoice_number", "line_ids": ["p1-l0001"], "quote": "INV-7"}],
        "issues": [],
    }
    responses = FakeResponses([invalid, valid])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.get_openai_client",
        lambda: SimpleNamespace(responses=responses),
    )
    catalog = [LineEvidence("p1-l0001", 1, "Invoice INV-7", (1, 2, 3, 4), "ocr_300")]
    result, prompt_hash = extract_data(
        "Invoice INV-7", catalog, ProcessingOptions("Extract invoice number", strict_schema())
    )
    assert result["status"] == "complete"
    assert len(responses.calls) == 2
    assert len(prompt_hash) == 64
    assert "unknown or empty line IDs" in responses.calls[1]["input"]
    assert responses.calls[0]["model"] == "gpt-5.6-terra"
    assert responses.calls[0]["reasoning"] == {"effort": "medium"}
    assert responses.calls[0]["store"] is False


def test_extraction_preserves_unresolved_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = {
        "status": "complete",
        "data": {"invoice_number": "INV-7"},
        "evidence": [{"path": "/bad", "line_ids": ["p1-l0001"], "quote": "wrong"}],
        "issues": [],
    }
    responses = FakeResponses([invalid, invalid.copy()])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.get_openai_client",
        lambda: SimpleNamespace(responses=responses),
    )
    catalog = [LineEvidence("p1-l0001", 1, "Invoice INV-7", (1, 2, 3, 4), "ocr_300")]
    result, _ = extract_data(
        "Invoice INV-7", catalog, ProcessingOptions("Extract", strict_schema())
    )
    assert result["status"] == "partial"
    assert {issue["code"] for issue in result["issues"]} == {"invalid_evidence"}


def test_artifact_exports() -> None:
    first = DocumentArtifact(
        "Invoice 1.pdf",
        b"pdf",
        "a" * 64,
        status=RunStatus.COMPLETE,
        markdown="# One",
        output={"status": "complete"},
    )
    second = DocumentArtifact(
        "Invoice 1.png",
        b"png",
        "b" * 64,
        status=RunStatus.PARTIAL,
        markdown="# Two",
        output={"status": "partial"},
    )
    failed = DocumentArtifact("bad.pdf", b"", "c" * 64, status=RunStatus.FAILED)
    assert json.loads(artifact_json(first))["status"] == "complete"
    with zipfile.ZipFile(io.BytesIO(result_zip([first, second, failed]))) as archive:
        assert archive.namelist() == [
            "Invoice_1.md",
            "Invoice_1.json",
            "Invoice_1-bbbbbbbb.md",
            "Invoice_1-bbbbbbbb.json",
        ]
        assert archive.read("Invoice_1.md") == b"# One"


class FakeTextItem:
    text = "Invoice INV-7"
    x = 10.0
    y = 20.0
    width = 30.0
    height = 8.0
    confidence = 0.9


class FakePage:
    page_num = 1
    width = 72.0
    height = 72.0
    text_items: ClassVar[list[FakeTextItem]] = [FakeTextItem()]
    blocks: ClassVar[list[Any]] = []


def fake_result(image: bytes, total_pages: int = 1) -> SimpleNamespace:
    shot = SimpleNamespace(page_num=1, width=100, height=100, image_bytes=image)
    return SimpleNamespace(
        total_pages=total_pages,
        pages=[FakePage()],
        screenshots=[shot],
        text="# Invoice\n\nINV-7",
        page_errors=[],
    )


def test_line_catalog_and_prompt() -> None:
    catalog = _line_catalog(fake_result(png_bytes()), {1: [(0, 0, 50, 50)]})
    assert catalog[0].source == "repair_400"
    assert "p1-l0001" in _catalog_prompt(catalog)


def test_hard_regions_include_ocr_and_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    image = png_bytes()
    block = SimpleNamespace(
        kind="grid_fallback", bbox=SimpleNamespace(x=36.0, y=36.0, width=18.0, height=18.0)
    )
    page = SimpleNamespace(page_num=1, width=72.0, height=72.0, blocks=[block])
    shot = SimpleNamespace(page_num=1, width=100, height=100, image_bytes=image)
    result = SimpleNamespace(pages=[page], screenshots=[shot])
    ocr_record = SimpleNamespace(hard_regions=[SimpleNamespace(bbox=(5, 5, 10, 10), reason="tiny")])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.REGISTRY.base_record",
        lambda *_: ocr_record,
    )
    regions = _hard_regions(result, "run")
    assert len(regions) == 2
    assert {region.reason for region, _digest in regions} == {"tiny", "LiteParse grid fallback"}


def test_process_document_without_repairs(monkeypatch: pytest.MonkeyPatch) -> None:
    image = png_bytes()
    result = fake_result(image)

    class FakeLiteParse:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def parse(self, _source: Any) -> SimpleNamespace:
            return result

    monkeypatch.setattr("liteparse_agentic_document_extraction.pipeline.LiteParse", FakeLiteParse)
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline._hard_regions", lambda *_: []
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.extract_data",
        lambda *_: (
            {
                "status": "complete",
                "data": {"document_type": "invoice", "fields": []},
                "evidence": [
                    {"path": "/data/document_type", "line_ids": ["p1-l0001"], "quote": "Invoice"}
                ],
                "issues": [],
            },
            "e" * 64,
        ),
    )
    artifact = process_document("invoice.png", image, ProcessingOptions("Extract"))
    assert artifact.status == RunStatus.COMPLETE
    assert artifact.markdown.startswith("# Invoice")
    assert artifact.output["evidence"][0]["sources"][0]["id"] == "p1-l0001"
    assert artifact.output["document"]["base_dpi"] == 300


def test_process_document_with_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    image = png_bytes()
    result = fake_result(image)
    parse_calls: list[dict[str, Any]] = []

    class FakeLiteParse:
        def __init__(self, **kwargs: Any) -> None:
            parse_calls.append(kwargs)

        def parse(self, _source: Any) -> SimpleNamespace:
            return result

    monkeypatch.setattr("liteparse_agentic_document_extraction.pipeline.LiteParse", FakeLiteParse)
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline._hard_regions",
        lambda *_: [(Region(1, (20, 20, 60, 60), "blur"), "digest")],
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.REGISTRY.repair_record",
        lambda *_: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.REGISTRY.patch_base",
        lambda *_: (2, 1),
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.pipeline.extract_data",
        lambda *_: (
            {"status": "partial", "data": None, "evidence": [], "issues": []},
            "e" * 64,
        ),
    )
    artifact = process_document("invoice.png", image, ProcessingOptions("Extract"))
    assert artifact.status == RunStatus.PARTIAL
    assert artifact.output["repairs"][0]["replaced_lines"] == 2
    assert any(call.get("dpi") == 400 for call in parse_calls)
    assert any(
        call.get("ocr_server_headers", {}).get("X-OCR-Stage") == "final" for call in parse_calls
    )


def test_process_document_rejects_too_many_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    image = png_bytes()

    class FakeLiteParse:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def parse(self, _source: Any) -> SimpleNamespace:
            return fake_result(image, total_pages=101)

    monkeypatch.setattr("liteparse_agentic_document_extraction.pipeline.LiteParse", FakeLiteParse)
    artifact = process_document("invoice.png", image, ProcessingOptions("Extract"))
    assert artifact.status == RunStatus.FAILED
    assert artifact.error == "Document exceeds 100 pages; select at most 100 pages"


def test_process_document_contains_invalid_upload_failure() -> None:
    artifact = process_document("notes.txt", b"hello", ProcessingOptions("Extract"))

    assert artifact.status == RunStatus.FAILED
    assert artifact.error == "Unsupported file type: .txt"
