"""Conservative agreement rules for repeated Terra OCR reads.

Used two ways: resolve_ocr_reads compares independent Terra calls on the same
image (repair.py's accuracy policy), and has_ocr_anomaly flags a single read
as suspect enough to trigger a repair in the first place. Next: ocr_bridge.py,
which calls resolve_ocr_reads, and repair.py, which calls has_ocr_anomaly.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .models import OcrLine

# Below this IoU, two boxes for the "same" line are treated as pointing at
# different text rather than a minor rendering jitter.
MIN_BOX_IOU = 0.35


@dataclass(frozen=True, slots=True)
class OcrConsensus:
    """Accepted lines and how many independent reads were required."""

    lines: tuple[OcrLine, ...]
    status: str
    calls: int

    @property
    def accepted(self) -> bool:
        return self.status in {"consensus", "majority"}


def normalized_ocr_text(value: str) -> str:
    """Normalize encoding and spacing without changing visible characters or case."""
    return " ".join(unicodedata.normalize("NFC", value).split())


def box_iou(first: list[float], second: list[float]) -> float:
    """Return intersection over union for two ordered OCR pixel boxes."""
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if not intersection:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def resolve_ocr_reads(
    first: list[OcrLine],
    second: list[OcrLine],
    third: list[OcrLine] | None = None,
) -> OcrConsensus:
    """Accept complete two-read agreement or a complete per-line two-of-three majority.

    Comparison is strictly positional: reads are compared line-by-line by
    index, with no re-alignment. A read that segments the region into a
    different number of lines is an automatic disagreement, even if the text
    content would otherwise agree.
    """
    reads = (first, second) if third is None else (first, second, third)
    calls = len(reads)
    if not first or any(len(read) != len(first) for read in reads[1:]):
        return OcrConsensus((), "disagreement", calls)

    chosen: list[OcrLine] = []
    for index in range(len(first)):
        candidates = [read[index] for read in reads]
        groups: dict[str, list[OcrLine]] = {}
        for candidate in candidates:
            groups.setdefault(normalized_ocr_text(candidate.text), []).append(candidate)
        agreeing = max(groups.values(), key=len)
        required = 2
        if len(agreeing) < required:
            return OcrConsensus((), "disagreement", calls)
        if any(box_iou(agreeing[0].bbox, item.bbox) < MIN_BOX_IOU for item in agreeing[1:]):
            return OcrConsensus((), "disagreement", calls)
        chosen.append(agreeing[0])

    return OcrConsensus(tuple(chosen), "consensus" if calls == 2 else "majority", calls)


def has_ocr_anomaly(text: str) -> bool:
    """Detect transcription artifacts that justify a targeted reread.

    Three independent signals, any one sufficient: the model's own
    illegibility marker, the Unicode replacement character (a decoding
    failure), stray control characters, or an 8-repeat run of one character
    (a common stuck-scan/garbled-OCR pattern). This drives repair.py's
    decision to spend a 400-DPI reread on a line, so a false positive costs
    OCR calls rather than correctness.
    """
    if "[ILLEGIBLE_TEXT]" in text or "\ufffd" in text:
        return True
    if any(ord(char) < 32 and char not in "\t\n\r" for char in text):
        return True
    return any(character * 8 in text for character in set(text))
