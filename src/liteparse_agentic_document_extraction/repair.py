"""Deep LiteParse module for base parsing and transactional 400-DPI repair."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liteparse import LiteParse

from .models import (
    BBox,
    LineEvidence,
    OcrLine,
    OcrStage,
    ParsedDocument,
    ParsedPage,
    ProcessingIssue,
    ProcessingOptions,
    RepairReceipt,
)
from .ocr_bridge import REGISTRY, OcrPageRecord, image_digest
from .settings import (
    BASE_DPI,
    MAX_PAGES,
    MAX_REPAIRS_PER_DOCUMENT,
    MAX_REPAIRS_PER_PAGE,
    OCR_URL,
    REPAIR_DPI,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Region:
    """Hard region in base screenshot pixels."""

    page: int
    bbox: BBox
    reason: str


def _boxes_touch(first: BBox, second: BBox, gap: float) -> bool:
    return not (
        first[2] + gap < second[0]
        or second[2] + gap < first[0]
        or first[3] + gap < second[1]
        or second[3] + gap < first[1]
    )


def merge_regions(regions: Iterable[Region], width: int, height: int) -> list[Region]:
    """Merge overlapping or nearby hard regions without hiding budget overflow."""
    merged: list[Region] = []
    gap = max(width, height) * 0.01
    for region in regions:
        current = region
        index = 0
        while index < len(merged):
            other = merged[index]
            if other.page == current.page and _boxes_touch(other.bbox, current.bbox, gap):
                a, b = other.bbox, current.bbox
                current = Region(
                    current.page,
                    (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])),
                    f"{other.reason}; {current.reason}"[:200],
                )
                merged.pop(index)
                index = 0
            else:
                index += 1
        merged.append(current)
    return sorted(merged, key=lambda item: (item.page, item.bbox[1], item.bbox[0]))


def padded_crop(bbox: BBox, width: int, height: int) -> BBox:
    """Convert a pixel bbox to LiteParse fractional crop values with 2% padding."""
    x1, y1, x2, y2 = bbox
    pad_x, pad_y = width * 0.02, height * 0.02
    left = max(0.0, x1 - pad_x) / width
    top = max(0.0, y1 - pad_y) / height
    right = 1.0 - min(float(width), x2 + pad_x) / width
    bottom = 1.0 - min(float(height), y2 + pad_y) / height
    return top, right, bottom, left


def _parser(
    options: ProcessingOptions, run_id: str, stage: OcrStage, **overrides: Any
) -> LiteParse:
    settings: dict[str, Any] = {
        "ocr_enabled": True,
        "ocr_server_url": OCR_URL,
        "ocr_server_headers": {"X-Run-ID": run_id, "X-OCR-Stage": stage.value},
        "ocr_language": options.language,
        "max_pages": MAX_PAGES,
        "target_pages": options.target_pages,
        "dpi": BASE_DPI,
        "output_format": "markdown",
        "image_mode": options.image_mode,
        "keep_headers_footers": options.keep_headers_footers,
        "extract_screenshots": True,
        "extract_blocks": True,
        "include_complexity": True,
        "continue_on_page_error": True,
        "ocr_failure_fatal": True,
        "num_workers": 1,
        "quiet": True,
    }
    settings.update(overrides)
    return LiteParse(**settings)


def _page_regions(result: Any, run_id: str) -> list[tuple[Region, str]]:
    candidates: list[tuple[Region, str]] = []
    pages = {page.page_num: page for page in result.pages}
    for screenshot in result.screenshots:
        digest, width, height = image_digest(screenshot.image_bytes)
        record = REGISTRY.base_record(run_id, digest)
        if record is None:
            continue
        page = pages[screenshot.page_num]
        regions = [
            Region(
                screenshot.page_num,
                (region.bbox[0], region.bbox[1], region.bbox[2], region.bbox[3]),
                region.reason,
            )
            for region in record.hard_regions
        ]
        for block in page.blocks or []:
            if block.kind == "grid_fallback" and block.bbox is not None:
                box = block.bbox
                regions.append(
                    Region(
                        page.page_num,
                        (
                            box.x / page.width * width,
                            box.y / page.height * height,
                            (box.x + box.width) / page.width * width,
                            (box.y + box.height) / page.height * height,
                        ),
                        "LiteParse grid fallback",
                    )
                )
        merged = merge_regions(regions, width, height)
        candidates.extend((region, digest) for region in merged)
    return candidates


def _inside(box: list[float] | BBox, inner: BBox) -> bool:
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    return inner[0] <= center_x <= inner[2] and inner[1] <= center_y <= inner[3]


def _fingerprint(line: OcrLine) -> tuple[str, float, float, float, float]:
    return (
        line.text,
        round(line.bbox[0], 2),
        round(line.bbox[1], 2),
        round(line.bbox[2], 2),
        round(line.bbox[3], 2),
    )


def apply_repair(
    base: OcrPageRecord,
    inner_box: BBox,
    crop_box: BBox,
    repair: OcrPageRecord,
) -> tuple[int, int]:
    """Atomically replace base lines only when valid 400-DPI lines map back."""
    left = crop_box[3] * base.width
    top = crop_box[0] * base.height
    scale_x = (1.0 - crop_box[1] - crop_box[3]) * base.width / repair.width
    scale_y = (1.0 - crop_box[0] - crop_box[2]) * base.height / repair.height
    mapped: list[OcrLine] = []
    for line in repair.results:
        x1, y1, x2, y2 = line.bbox
        box = (
            left + x1 * scale_x,
            top + y1 * scale_y,
            left + x2 * scale_x,
            top + y2 * scale_y,
        )
        if not _inside(box, inner_box):
            continue
        polygon = None
        if line.polygon:
            polygon = [
                [left + point[0] * scale_x, top + point[1] * scale_y] for point in line.polygon
            ]
        mapped.append(line.model_copy(update={"bbox": list(box), "polygon": polygon}))

    if not mapped:
        return 0, 0
    preserved = [line for line in base.results if not _inside(line.bbox, inner_box)]
    removed = len(base.results) - len(preserved)
    base.results = sorted(preserved + mapped, key=lambda line: (line.bbox[1], line.bbox[0]))
    base.repaired_fingerprints.update(_fingerprint(line) for line in mapped)
    return removed, len(mapped)


def _iou(first: BBox, second: BBox) -> float:
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection == 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def _line_catalog(result: Any, run_id: str) -> tuple[LineEvidence, ...]:
    screenshots = {shot.page_num: shot for shot in result.screenshots}
    catalog: list[LineEvidence] = []
    for page in result.pages:
        shot = screenshots.get(page.page_num)
        record = None
        ocr_lines: list[tuple[OcrLine, BBox]] = []
        if shot is not None:
            digest, _, _ = image_digest(shot.image_bytes)
            record = REGISTRY.base_record(run_id, digest)
            if record:
                ocr_lines = [
                    (
                        line,
                        (
                            line.bbox[0] / shot.width * page.width,
                            line.bbox[1] / shot.height * page.height,
                            line.bbox[2] / shot.width * page.width,
                            line.bbox[3] / shot.height * page.height,
                        ),
                    )
                    for line in record.results
                ]
        for index, item in enumerate(page.text_items, start=1):
            box = (item.x, item.y, item.x + item.width, item.y + item.height)
            source, confidence = "native", None
            matches = [
                (candidate, candidate_box)
                for candidate, candidate_box in ocr_lines
                if candidate.text.strip() == item.text.strip()
            ]
            if matches:
                candidate, _ = max(matches, key=lambda pair: _iou(box, pair[1]))
                if max(_iou(box, pair[1]) for pair in matches) >= 0.35:
                    confidence = candidate.confidence
                    source = (
                        "repair_400"
                        if record and _fingerprint(candidate) in record.repaired_fingerprints
                        else "ocr_300"
                    )
            catalog.append(
                LineEvidence(
                    id=f"p{page.page_num}-l{index:04d}",
                    page=page.page_num,
                    text=item.text,
                    bbox=box,
                    source=source,
                    confidence=confidence,
                )
            )
    return tuple(catalog)


def parse_document(
    source: Path, options: ProcessingOptions, selected: list[int] | None
) -> ParsedDocument:
    """Parse one document and apply bounded hard-region repair behind one interface."""
    run_id = REGISTRY.start()
    issues: list[ProcessingIssue] = []
    receipts: list[RepairReceipt] = []
    try:
        preflight = LiteParse(ocr_enabled=False, max_pages=1, quiet=True).parse(source)
        if selected and max(selected) > preflight.total_pages:
            raise ValueError("Page selection exceeds document page count")
        if not selected and preflight.total_pages > MAX_PAGES:
            raise ValueError("Document exceeds 100 pages; select at most 100 pages")

        base_result = _parser(options, run_id, OcrStage.BASE).parse(source)
        candidates = _page_regions(base_result, run_id)
        per_page: dict[int, int] = {}
        bounded_candidates: list[tuple[Region, str]] = []
        per_page_skipped = 0
        for candidate in candidates:
            page_number = candidate[0].page
            count = per_page.get(page_number, 0)
            if count >= MAX_REPAIRS_PER_PAGE:
                per_page_skipped += 1
                continue
            per_page[page_number] = count + 1
            bounded_candidates.append(candidate)
        candidates = bounded_candidates
        if per_page_skipped:
            issues.append(
                ProcessingIssue(
                    "repair_page_budget_exceeded",
                    f"Skipped {per_page_skipped} hard regions after per-page repair limits",
                    "repair",
                )
            )
        if len(candidates) > MAX_REPAIRS_PER_DOCUMENT:
            skipped = len(candidates) - MAX_REPAIRS_PER_DOCUMENT
            issues.append(
                ProcessingIssue(
                    "repair_budget_exceeded",
                    f"Skipped {skipped} hard regions after the 64-repair document limit",
                    "repair",
                )
            )
            candidates = candidates[:MAX_REPAIRS_PER_DOCUMENT]

        shots = {shot.page_num: shot for shot in base_result.screenshots}
        pages = {page.page_num: page for page in base_result.pages}
        for number, (region, digest) in enumerate(candidates, start=1):
            shot = shots[region.page]
            crop = padded_crop(region.bbox, shot.width, shot.height)
            region_id = f"p{region.page}-r{number:03d}"
            try:
                repair_parser = _parser(
                    options,
                    run_id,
                    OcrStage.REPAIR,
                    ocr_server_headers={
                        "X-Run-ID": run_id,
                        "X-OCR-Stage": OcrStage.REPAIR.value,
                        "X-Region-ID": region_id,
                    },
                    dpi=REPAIR_DPI,
                    target_pages=str(region.page),
                    crop_box=crop,
                    extract_screenshots=False,
                    include_complexity=False,
                )
                repair_parser.parse(source)
                repair = REGISTRY.repair_record(run_id, region_id)
                base = REGISTRY.base_record(run_id, digest)
                if repair is None or base is None:
                    raise RuntimeError("repair OCR returned no usable record")
                removed, added = apply_repair(base, region.bbox, crop, repair)
                if not added:
                    raise RuntimeError("repair OCR returned no valid mapped lines")
                page = pages[region.page]
                point_box = (
                    region.bbox[0] / shot.width * page.width,
                    region.bbox[1] / shot.height * page.height,
                    region.bbox[2] / shot.width * page.width,
                    region.bbox[3] / shot.height * page.height,
                )
                receipts.append(
                    RepairReceipt(region.page, region_id, point_box, region.reason, removed, added)
                )
            except Exception:
                LOGGER.exception("Hard-region repair failed for page %s", region.page)
                issues.append(
                    ProcessingIssue(
                        "repair_failed",
                        "400-DPI repair failed; retained the 300-DPI region",
                        "repair",
                        page=region.page,
                    )
                )

        final_result = base_result
        if receipts:
            try:
                final_result = _parser(options, run_id, OcrStage.FINAL).parse(source)
            except Exception:
                LOGGER.exception("Final repaired parse failed; using base parse")
                issues.append(
                    ProcessingIssue(
                        "final_parse_failed",
                        "Final repaired parse failed; retained base Markdown",
                        "repair",
                    )
                )
                receipts.clear()

        lines = _line_catalog(final_result, run_id)
        line_ids_by_page: dict[int, list[str]] = {}
        for line in lines:
            line_ids_by_page.setdefault(line.page, []).append(line.id)
        parsed_pages = tuple(
            ParsedPage(
                page.page_num,
                page.markdown or page.text,
                tuple(line_ids_by_page.get(page.page_num, [])),
            )
            for page in final_result.pages
        )
        for error in final_result.page_errors:
            issues.append(
                ProcessingIssue(
                    "page_error",
                    str(error)[:500],
                    "parsing",
                    page=getattr(error, "page_num", None),
                )
            )
        prompt_hashes = {
            prompt_hash
            for screenshot in final_result.screenshots
            if (record := REGISTRY.base_record(run_id, image_digest(screenshot.image_bytes)[0]))
            for prompt_hash in record.prompt_hashes
        }
        return ParsedDocument(
            markdown=final_result.text,
            pages=parsed_pages,
            lines=lines,
            repairs=tuple(receipts),
            issues=tuple(issues),
            source_page_count=preflight.total_pages,
            processed_pages=tuple(page.page_num for page in final_result.pages),
            prompt_template_hashes=tuple(sorted(prompt_hashes)),
        )
    finally:
        REGISTRY.finish(run_id)
