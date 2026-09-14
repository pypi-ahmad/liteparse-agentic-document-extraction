"""Tests for visual annotated PDF generation."""

import io
from types import SimpleNamespace

from PIL import Image, ImageDraw

from liteparse_agentic_document_extraction.annotations import _draw_line_box, build_annotated_pdf
from liteparse_agentic_document_extraction.models import LineEvidence


def test_build_annotated_pdf_from_page_screenshot() -> None:
    image_bytes = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(image_bytes, format="PNG")
    screenshot = SimpleNamespace(page_num=1, image_bytes=image_bytes.getvalue())
    page = SimpleNamespace(page_num=1, width=72, height=72)
    lines = [LineEvidence("p1-l0001", 1, "Text", (12, 12, 60, 24), "ocr_300", 0.9)]

    annotated = build_annotated_pdf([screenshot], [page], lines)

    assert annotated.startswith(b"%PDF-")


def test_build_annotated_pdf_returns_empty_without_matching_pages() -> None:
    assert build_annotated_pdf([], [], []) == b""


def test_repair_annotation_is_a_thin_padded_box() -> None:
    image = Image.new("RGB", (300, 300), "white")
    line = LineEvidence("p1-l0001", 1, "Text", (12, 12, 60, 24), "repair_400", 0.9)

    _draw_line_box(ImageDraw.Draw(image), line, 4, 4, default_width=3)

    assert image.getpixel((40, 40)) == (220, 38, 38)
    assert image.getpixel((48, 48)) == (255, 255, 255)
