"""Tests for conservative document-local peer selection."""

import io
from types import SimpleNamespace

from PIL import Image, ImageDraw

from liteparse_agentic_document_extraction.models import OcrLine
from liteparse_agentic_document_extraction.ocr_bridge import OcrPageRecord, image_digest
from liteparse_agentic_document_extraction.peer_evidence import select_peer_evidence


def page_image(detailed: bool) -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    if detailed:
        draw = ImageDraw.Draw(image)
        for offset in range(10, 190, 4):
            draw.line((offset, 20, offset, 50), fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def result_and_records(
    text: str = "Stable heading",
) -> tuple[SimpleNamespace, dict[int, OcrPageRecord]]:
    pages = []
    screenshots = []
    records = {}
    for number, detailed in ((1, False), (2, True), (3, True)):
        image = page_image(detailed)
        block = SimpleNamespace(
            kind="heading",
            text=text,
            lines=None,
            bbox=SimpleNamespace(x=10, y=10, width=50, height=20),
        )
        pages.append(SimpleNamespace(page_num=number, width=100, height=50, blocks=[block]))
        screenshots.append(
            SimpleNamespace(page_num=number, width=200, height=100, image_bytes=image)
        )
        digest, width, height = image_digest(image)
        records[number] = OcrPageRecord(
            digest,
            width,
            height,
            [
                OcrLine(
                    text=text,
                    bbox=(20, 20, 120, 60),
                    confidence=0.9,
                    source_kind="printed",
                )
            ],
            [],
            ("h",),
        )
    return SimpleNamespace(pages=pages, screenshots=screenshots), records


def test_peer_requires_two_clearer_matching_printed_pages() -> None:
    result, records = result_and_records()
    peer = select_peer_evidence(result, records, 1, (20, 20, 120, 60))
    assert peer is not None
    assert peer.source_page in {2, 3}


def test_peer_rejects_variable_or_nonprinted_content() -> None:
    result, records = result_and_records("Page 12")
    assert select_peer_evidence(result, records, 1, (20, 20, 120, 60)) is None

    result, records = result_and_records()
    records[2].results[0].source_kind = "handwritten"
    assert select_peer_evidence(result, records, 1, (20, 20, 120, 60)) is None
