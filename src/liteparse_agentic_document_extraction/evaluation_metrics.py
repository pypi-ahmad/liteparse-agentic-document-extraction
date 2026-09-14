"""Deterministic Markdown, table, line, and grounding evaluation metrics.

No model calls here; every score is a pure text/geometry comparison between a
ParsedDocument and a LandingAI ADE ground-truth export. The ADE JSON field
names this module reads (structure/grounding/range/box) are that external
format's shape, not ours - see knowledge/index.md's LandingAI ADE concept for
background. Next: evaluation.py, the only caller.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from typing import Any

from .consensus import box_iou, normalized_ocr_text
from .models import ParsedDocument, ParsedPage

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
PIPE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(normalize_inline("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def normalize_inline(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def normalize_markdown(value: str) -> str:
    """Normalize line endings and trailing whitespace while retaining layout lines."""
    lines = [line.rstrip() for line in unicodedata.normalize("NFC", value).splitlines()]
    return "\n".join(lines).strip()


def character_error_rate(reference: str, candidate: str) -> tuple[int, float, float]:
    edits = _levenshtein(reference, candidate)
    rate = edits / max(1, len(reference))
    return edits, rate, max(0.0, 1.0 - rate)


def precision_recall_f1(matched: int, candidate: int, reference: int) -> dict[str, float | int]:
    """Precision/recall/F1 with a fixed convention for empty inputs.

    An empty candidate against an empty reference scores 1.0 (correctly
    produced nothing); an empty candidate against a non-empty reference
    scores 0.0. This is a convention, not a general definition of precision.
    """
    precision = matched / candidate if candidate else float(reference == 0)
    recall = matched / reference if reference else float(candidate == 0)
    return {
        "matched": matched,
        "candidate": candidate,
        "reference": reference,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def headings(markdown: str) -> list[tuple[int, str]]:
    return [
        (len(match.group(1)), normalize_inline(match.group(2)))
        for line in normalize_markdown(markdown).splitlines()
        if (match := HEADING_RE.match(line))
    ]


def tables(markdown: str) -> list[list[list[str]]]:
    """Extract tables in either Markdown form LiteParse can emit: HTML <table> or pipe syntax."""
    parser = _HtmlTableParser()
    parser.feed(markdown)
    found = list(parser.tables)
    lines = markdown.splitlines()
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not PIPE_SEPARATOR_RE.match(lines[index + 1]):
            index += 1
            continue
        rows = [_pipe_cells(lines[index])]
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            rows.append(_pipe_cells(lines[index]))
            index += 1
        found.append(rows)
    return found


def evaluate_document(
    reference_pages: dict[int, str],
    reference_json: dict[str, Any],
    candidate: ParsedDocument,
) -> dict[str, Any]:
    candidate_pages = {page.page: page for page in candidate.pages}
    page_results = [
        evaluate_page(
            page_number,
            reference_markdown,
            _reference_atomic_lines(reference_json, page_number),
            candidate_pages.get(page_number),
            candidate,
        )
        for page_number, reference_markdown in sorted(reference_pages.items())
    ]
    reference_text = "\n\n".join(reference_pages.values())
    candidate_text = "\n\n".join(
        candidate_pages[page].markdown
        for page in sorted(reference_pages)
        if page in candidate_pages
    )
    return {
        "pages": page_results,
        "aggregate": _aggregate(reference_text, candidate_text, page_results),
    }


def evaluate_page(
    page_number: int,
    reference: str,
    reference_lines: list[tuple[str, list[float]]],
    candidate_page: ParsedPage | None,
    candidate: ParsedDocument,
) -> dict[str, Any]:
    if candidate_page is None:
        return {"page": page_number, "status": "failed"}
    raw = character_error_rate(reference, candidate_page.markdown)
    normalized = character_error_rate(
        normalize_markdown(reference), normalize_markdown(candidate_page.markdown)
    )
    candidate_lines = [line for line in candidate.lines if line.page == page_number]
    reference_counter = Counter(normalized_ocr_text(text) for text, _ in reference_lines if text)
    candidate_counter = Counter(
        normalized_ocr_text(line.text) for line in candidate_lines if line.text
    )
    matched = sum((reference_counter & candidate_counter).values())
    ious = _grounding_ious(reference_lines, candidate_lines, candidate_page)
    reference_tables, candidate_tables = tables(reference), tables(candidate_page.markdown)
    reference_cells = [cell for table in reference_tables for row in table for cell in row]
    candidate_cells = [cell for table in candidate_tables for row in table for cell in row]
    return {
        "page": page_number,
        "status": "ok",
        "raw_markdown": {"edits": raw[0], "cer": raw[1], "similarity": raw[2]},
        "normalized_markdown": {
            "edits": normalized[0],
            "cer": normalized[1],
            "similarity": normalized[2],
        },
        "headings": _sequence_f1(headings(reference), headings(candidate_page.markdown)),
        "table_shapes": _sequence_f1(
            [_table_shape(table) for table in reference_tables],
            [_table_shape(table) for table in candidate_tables],
        ),
        "table_cells": _sequence_f1(reference_cells, candidate_cells),
        "line_text": precision_recall_f1(
            matched, sum(candidate_counter.values()), sum(reference_counter.values())
        ),
        "grounding": {
            "matched": len(ious),
            "mean_iou": sum(ious) / len(ious) if ious else None,
        },
    }


def groundtruth_pages(data: dict[str, Any], selected: tuple[int, ...]) -> dict[int, str]:
    markdown = str(data.get("markdown", ""))
    root = data.get("structure", {})
    pages = root.get("children", []) if isinstance(root, dict) else []
    result = {}
    for page in pages:
        grounding = page.get("grounding", {})
        page_number = grounding.get("page")
        span = grounding.get("range", {})
        if page_number in selected:
            result[int(page_number)] = markdown[int(span["start"]) : int(span["end"])]
    missing = set(selected) - result.keys()
    if missing:
        raise ValueError(f"GroundTruth JSON is missing selected pages: {sorted(missing)}")
    return result


def _aggregate(reference: str, candidate: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    raw = character_error_rate(reference, candidate)
    normalized = character_error_rate(normalize_markdown(reference), normalize_markdown(candidate))
    valid = [page for page in pages if page["status"] == "ok"]
    return {
        "page_success_rate": len(valid) / max(1, len(pages)),
        "raw_markdown_cer": raw[1],
        "normalized_markdown_cer": normalized[1],
        "normalized_markdown_similarity": normalized[2],
        "heading_f1": _micro_f1(valid, "headings"),
        "table_shape_f1": _micro_f1(valid, "table_shapes"),
        "table_cell_f1": _micro_f1(valid, "table_cells"),
        "line_text_f1": _micro_f1(valid, "line_text"),
        "mean_grounding_iou": _mean_grounding(valid),
    }


def _reference_atomic_lines(
    data: dict[str, Any], page_number: int
) -> list[tuple[str, list[float]]]:
    markdown = str(data.get("markdown", ""))
    result: list[tuple[str, list[float]]] = []
    for page in data.get("structure", {}).get("children", []):
        if page.get("grounding", {}).get("page") != page_number:
            continue
        for child in page.get("children", []):
            for grounding in child.get("atomic_grounding", []):
                span = grounding.get("range", {})
                text = normalize_inline(markdown[int(span["start"]) : int(span["end"])])
                box = grounding.get("box")
                if text and isinstance(box, dict):
                    result.append((text, [box["xmin"], box["ymin"], box["xmax"], box["ymax"]]))
    return result


def _grounding_ious(
    reference: list[tuple[str, list[float]]], candidate: list[Any], page: ParsedPage
) -> list[float]:
    """Match candidate lines to reference lines by text, scored by box IoU.

    Greedy, in candidate order: each candidate line takes the best-IoU
    reference line among remaining same-text matches, then that reference
    line is consumed (`available.pop`) and cannot match again. This is not a
    globally optimal assignment, so repeated identical text on a page can be
    paired sub-optimally.
    """
    if not page.width or not page.height:
        return []
    available = list(reference)
    scores = []
    for line in candidate:
        key = normalized_ocr_text(line.text)
        matches = [
            (index, item)
            for index, item in enumerate(available)
            if normalized_ocr_text(item[0]) == key
        ]
        if not matches:
            continue
        candidate_box = [
            line.bbox[0] / page.width,
            line.bbox[1] / page.height,
            line.bbox[2] / page.width,
            line.bbox[3] / page.height,
        ]
        index, (_, reference_box) = max(
            matches, key=lambda item: box_iou(candidate_box, item[1][1])
        )
        scores.append(box_iou(candidate_box, reference_box))
        available.pop(index)
    return scores


def _pipe_cells(line: str) -> list[str]:
    return [normalize_inline(cell) for cell in line.strip().strip("|").split("|")]


def _table_shape(table: list[list[str]]) -> tuple[int, ...]:
    return tuple(len(row) for row in table)


def _sequence_f1(reference: list[Any], candidate: list[Any]) -> dict[str, float | int]:
    matched = sum((Counter(reference) & Counter(candidate)).values())
    return precision_recall_f1(matched, len(candidate), len(reference))


def _micro_f1(pages: list[dict[str, Any]], key: str) -> float:
    matched = sum(int(page[key]["matched"]) for page in pages)
    candidate = sum(int(page[key]["candidate"]) for page in pages)
    reference = sum(int(page[key]["reference"]) for page in pages)
    return float(precision_recall_f1(matched, candidate, reference)["f1"])


def _mean_grounding(pages: list[dict[str, Any]]) -> float | None:
    weighted = [
        (page["grounding"]["mean_iou"], page["grounding"]["matched"])
        for page in pages
        if page["grounding"]["mean_iou"] is not None
    ]
    count = sum(item[1] for item in weighted)
    return sum(item[0] * item[1] for item in weighted) / count if count else None


def _levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
