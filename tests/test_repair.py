"""Tests for the deep LiteParse repair module."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from PIL import Image

from liteparse_agentic_document_extraction.models import (
    HardRegion,
    LineEvidence,
    OcrLine,
    ProcessingOptions,
)
from liteparse_agentic_document_extraction.ocr_bridge import OcrPageRecord, image_digest
from liteparse_agentic_document_extraction.repair import (
    Region,
    _line_catalog,
    _page_regions,
    apply_repair,
    parse_document,
)


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(output, format="PNG")
    return output.getvalue()


class FakeTextItem:
    text = "Invoice INV-1"
    x = 10.0
    y = 20.0
    width = 30.0
    height = 8.0


class FakePage:
    page_num = 1
    width = 72.0
    height = 72.0
    text = "Invoice INV-1"
    markdown = "# Invoice\n\nINV-1"
    text_items: ClassVar[list[FakeTextItem]] = [FakeTextItem()]
    blocks: ClassVar[list[Any]] = []


def fake_result(image: bytes, total_pages: int = 1) -> SimpleNamespace:
    shot = SimpleNamespace(page_num=1, width=100, height=100, image_bytes=image)
    return SimpleNamespace(
        total_pages=total_pages,
        pages=[FakePage()],
        screenshots=[shot],
        text="# Invoice\n\nINV-1",
        page_errors=[],
    )


def record(image: bytes, lines: list[OcrLine]) -> OcrPageRecord:
    digest, width, height = image_digest(image)
    return OcrPageRecord(digest, width, height, lines, [], ("a" * 64,))


def test_parse_document_without_repairs(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    image = png_bytes()
    result = fake_result(image)

    class FakeLiteParse:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def parse(self, _source: Any) -> SimpleNamespace:
            return result

    monkeypatch.setattr("liteparse_agentic_document_extraction.repair.LiteParse", FakeLiteParse)
    monkeypatch.setattr("liteparse_agentic_document_extraction.repair._page_regions", lambda *_: [])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair._line_catalog",
        lambda *_: (LineEvidence("p1-l0001", 1, "Invoice INV-1", (10, 20, 40, 28), "ocr_300"),),
    )
    ocr_record = record(image, [])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair.REGISTRY.base_record",
        lambda *_: ocr_record,
    )
    source = tmp_path / "invoice.png"
    source.write_bytes(image)
    parsed = parse_document(source, ProcessingOptions("Extract"), None)
    assert parsed.markdown.startswith("# Invoice")
    assert parsed.processed_pages == (1,)
    assert parsed.prompt_template_hashes == ("a" * 64,)


def test_parse_document_applies_400_dpi_repair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    image = png_bytes()
    result = fake_result(image)
    calls: list[dict[str, Any]] = []

    class FakeLiteParse:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

        def parse(self, _source: Any) -> SimpleNamespace:
            return result

    base = record(
        image,
        [OcrLine(text="wrong", bbox=(20, 20, 60, 40), confidence=0.3)],
    )
    repair = record(
        image,
        [OcrLine(text="right", bbox=(20, 20, 60, 40), confidence=0.9)],
    )
    monkeypatch.setattr("liteparse_agentic_document_extraction.repair.LiteParse", FakeLiteParse)
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair._page_regions",
        lambda *_: [(Region(1, (10, 10, 80, 60), "blur"), base.digest)],
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair.REGISTRY.base_record",
        lambda *_: base,
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair.REGISTRY.repair_record",
        lambda *_: repair,
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair._line_catalog",
        lambda *_: (LineEvidence("p1-l0001", 1, "right", (10, 20, 40, 28), "repair_400"),),
    )
    source = tmp_path / "invoice.png"
    source.write_bytes(image)
    parsed = parse_document(source, ProcessingOptions("Extract"), None)
    assert parsed.repairs[0].added_lines == 1
    assert any(call.get("dpi") == 400 for call in calls)
    assert any(call.get("ocr_server_headers", {}).get("X-OCR-Stage") == "final" for call in calls)


def test_parse_document_rejects_page_overflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    image = png_bytes()

    class FakeLiteParse:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def parse(self, _source: Any) -> SimpleNamespace:
            return fake_result(image, total_pages=101)

    monkeypatch.setattr("liteparse_agentic_document_extraction.repair.LiteParse", FakeLiteParse)
    source = tmp_path / "invoice.png"
    source.write_bytes(image)
    with pytest.raises(ValueError, match="exceeds 100 pages"):
        parse_document(source, ProcessingOptions("Extract"), None)


def test_region_discovery_and_line_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    image = png_bytes()
    result = fake_result(image)
    result.pages[0].blocks = [
        SimpleNamespace(kind="grid_fallback", bbox=SimpleNamespace(x=10, y=10, width=20, height=20))
    ]
    base = OcrPageRecord(
        image_digest(image)[0],
        100,
        100,
        [OcrLine(text="Invoice INV-1", bbox=(14, 28, 56, 39), confidence=0.8)],
        [HardRegion(bbox=(10, 10, 50, 50), reason="blur")],
        ("h",),
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair.REGISTRY.base_record", lambda *_: base
    )
    regions = _page_regions(result, "run")
    assert regions and regions[0][0].reason
    catalog = _line_catalog(result, "run")
    assert catalog[0].bbox == (10, 20, 40, 28)
    assert catalog[0].source == "ocr_300"
    assert catalog[0].confidence == 0.8

    base.repaired_fingerprints.add(("Invoice INV-1", 14.0, 28.0, 56.0, 39.0))
    assert _line_catalog(result, "run")[0].source == "repair_400"


def test_apply_repair_maps_polygon_and_rejects_outside_lines() -> None:
    image = png_bytes()
    base = record(image, [OcrLine(text="old", bbox=(20, 20, 40, 30), confidence=0.2)])
    outside = record(image, [OcrLine(text="outside", bbox=(80, 80, 90, 90), confidence=0.9)])
    assert apply_repair(base, (10, 10, 50, 50), (0.0, 0.0, 0.0, 0.0), outside) == (0, 0)
    assert base.results[0].text == "old"

    repaired = record(
        image,
        [
            OcrLine(
                text="new",
                bbox=(20, 20, 40, 30),
                polygon=[[20, 20], [40, 20], [40, 30], [20, 30]],
                confidence=0.9,
            )
        ],
    )
    assert apply_repair(base, (10, 10, 50, 50), (0.0, 0.0, 0.0, 0.0), repaired) == (1, 1)
    assert base.results[0].polygon == [[20.0, 20.0], [40.0, 20.0], [40.0, 30.0], [20.0, 30.0]]


def test_parse_document_records_limits_failures_and_page_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    image = png_bytes()
    result = fake_result(image)
    result.page_errors = [SimpleNamespace(page_num=1, __str__=lambda _self: "bad page")]
    base = record(image, [OcrLine(text="old", bbox=(20, 20, 40, 30), confidence=0.2)])

    class FakeLiteParse:
        calls = 0

        def __init__(self, **_kwargs: Any) -> None:
            pass

        def parse(self, _source: Any) -> SimpleNamespace:
            self.__class__.calls += 1
            if self.__class__.calls > 2:
                raise RuntimeError("repair failed")
            return result

    candidates = [
        (Region(1, (10 + index, 10, 20 + index, 20), "hard"), base.digest) for index in range(10)
    ]
    monkeypatch.setattr("liteparse_agentic_document_extraction.repair.LiteParse", FakeLiteParse)
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair._page_regions", lambda *_: candidates
    )
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.repair.REGISTRY.base_record", lambda *_: base
    )
    monkeypatch.setattr("liteparse_agentic_document_extraction.repair._line_catalog", lambda *_: ())
    source = tmp_path / "scan.png"
    source.write_bytes(image)
    parsed = parse_document(source, ProcessingOptions("Extract"), None)
    assert {issue.code for issue in parsed.issues} == {
        "repair_page_budget_exceeded",
        "repair_failed",
        "page_error",
    }


def test_parse_document_rejects_selected_page_overflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    image = png_bytes()

    class FakeLiteParse:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def parse(self, _source: Any) -> SimpleNamespace:
            return fake_result(image)

    monkeypatch.setattr("liteparse_agentic_document_extraction.repair.LiteParse", FakeLiteParse)
    source = tmp_path / "scan.png"
    source.write_bytes(image)
    with pytest.raises(ValueError, match="selection"):
        parse_document(source, ProcessingOptions("Extract"), [2])
