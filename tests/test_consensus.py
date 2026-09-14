"""Tests for conservative multi-read OCR agreement."""

from liteparse_agentic_document_extraction.consensus import has_ocr_anomaly, resolve_ocr_reads
from liteparse_agentic_document_extraction.models import OcrLine


def line(text: str, box: tuple[float, float, float, float] = (1, 2, 20, 10)) -> OcrLine:
    return OcrLine(text=text, bbox=box, confidence=0.8)


def test_two_reads_accept_only_text_and_geometry_agreement() -> None:
    result = resolve_ocr_reads([line("Café  12")], [line("Cafe\u0301 12", (2, 2, 21, 10))])
    assert result.accepted
    assert result.status == "consensus"
    assert result.calls == 2

    assert not resolve_ocr_reads([line("ABC")], [line("ABD")]).accepted
    assert not resolve_ocr_reads([line("ABC")], [line("ABC", (40, 40, 60, 50))]).accepted


def test_third_read_resolves_each_line_by_majority() -> None:
    result = resolve_ocr_reads(
        [line("A"), line("wrong")],
        [line("A"), line("B")],
        [line("different"), line("B")],
    )
    assert [item.text for item in result.lines] == ["A", "B"]
    assert result.status == "majority"
    assert result.calls == 3


def test_consensus_rejects_incomplete_or_unresolved_regions() -> None:
    assert not resolve_ocr_reads([line("A")], []).accepted
    assert not resolve_ocr_reads([line("A")], [line("B")], [line("C")]).accepted


def test_ocr_anomaly_signals_are_non_correcting() -> None:
    assert has_ocr_anomaly("[ILLEGIBLE_TEXT]")
    assert has_ocr_anomaly("11111111")
    assert has_ocr_anomaly("bad\ufffdtext")
    assert not has_ocr_anomaly("Invoice INV-17")
