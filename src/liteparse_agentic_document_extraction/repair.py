"""Deep LiteParse module for base parsing and transactional 400-DPI repair.

"Transactional" means apply_repair only ever mutates a page's OCR results
together with a successful, non-empty replacement; a failed or empty repair
leaves the 300-DPI base reading untouched (see apply_repair and the
`if not added: raise` check in parse_document below). Repair failures are
recorded as ProcessingIssue entries, not raised past this module, so one bad
region never fails a whole document. Next: pipeline.py's process_document,
the only caller of parse_document.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liteparse import LiteParse

from .annotations import build_annotated_pdf
from .consensus import has_ocr_anomaly
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
from .peer_evidence import records_by_page, select_peer_evidence
from .settings import (
    BASE_DPI,
    LOW_CONFIDENCE_THRESHOLD,
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
    """Merge overlapping or nearby hard regions without hiding budget overflow.

    Regions within 1% of the page's larger dimension are joined into one so
    that one visually contiguous problem area costs one repair-budget slot
    (see MAX_REPAIRS_PER_PAGE) instead of several adjacent ones.
    """
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
    """Convert a pixel bbox to LiteParse fractional crop values with 2% padding.

    Return order is (top, right, bottom, left) - LiteParse's crop_box
    convention - not the (x1, y1, x2, y2) order used by every other BBox in
    this file. right/bottom are fractions cropped *away* from that edge, not
    absolute positions, hence the `1.0 - ...`.
    """
    x1, y1, x2, y2 = bbox
    pad_x, pad_y = width * 0.02, height * 0.02
    left = max(0.0, x1 - pad_x) / width
    top = max(0.0, y1 - pad_y) / height
    right = 1.0 - min(float(width), x2 + pad_x) / width
    bottom = 1.0 - min(float(height), y2 + pad_y) / height
    return top, right, bottom, left


def _parser(
    options: ProcessingOptions,
    run_id: str,
    stage: OcrStage,
    *,
    ocr_url: str = OCR_URL,
    **overrides: Any,
) -> LiteParse:
    settings: dict[str, Any] = {
        "ocr_enabled": True,
        "ocr_server_url": ocr_url,
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
        # A single page's own parse error is tolerated (continue_on_page_error)
        # and surfaces later as a ProcessingIssue; an OCR-callback failure is
        # not - it aborts the whole LiteParse.parse() call below, which every
        # caller in this module wraps in a try/except to convert to an issue.
        "continue_on_page_error": True,
        "ocr_failure_fatal": True,
        "num_workers": 1,
        "quiet": True,
    }
    settings["ocr_server_headers"]["X-Accuracy-Policy"] = options.accuracy_policy.value
    settings.update(overrides)
    return LiteParse(**settings)


def _page_regions(
    result: Any, run_id: str, options: ProcessingOptions | None = None
) -> list[tuple[Region, str]]:
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
        # Legacy policy only repairs regions Terra explicitly flagged as hard;
        # accuracy policy (the default, and callers with no options at all)
        # additionally treats a low-confidence or anomalous line as its own
        # repair candidate.
        if options is None or options.accuracy_policy.value == "accuracy":
            for line in record.results:
                reasons = []
                if line.confidence < LOW_CONFIDENCE_THRESHOLD:
                    reasons.append(f"OCR confidence below {LOW_CONFIDENCE_THRESHOLD:.2f}")
                if has_ocr_anomaly(line.text):
                    reasons.append("OCR anomaly")
                if reasons:
                    regions.append(
                        Region(
                            screenshot.page_num,
                            (line.bbox[0], line.bbox[1], line.bbox[2], line.bbox[3]),
                            "; ".join(reasons),
                        )
                    )
        # A LiteParse "grid_fallback" block means layout detection could not
        # confidently reconstruct a table/grid in that region; always repair
        # it regardless of OCR confidence, since the risk here is structural,
        # not textual.
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
    """Atomically replace base lines only when valid 400-DPI lines map back.

    crop_box is (top, right, bottom, left) fractions of the base image (see
    padded_crop); left/top here recover that crop's absolute pixel origin in
    base-image space, and scale_x/scale_y convert repair-image pixels back
    to that same base-image pixel space so mapped boxes are directly
    comparable to base.results.
    """
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
        # Center-point containment, not IoU: cheap, and sufficient because
        # padded_crop already pads the region by 2%, so a line that truly
        # belongs to this repair rarely straddles the boundary.
        if not _inside(box, inner_box):
            continue
        polygon = None
        if line.polygon:
            polygon = [
                [left + point[0] * scale_x, top + point[1] * scale_y] for point in line.polygon
            ]
        mapped.append(line.model_copy(update={"bbox": list(box), "polygon": polygon}))

    # Nothing to replace with: leave base.results completely untouched rather
    # than deleting the old lines and ending up with a hole (the
    # "transactional" guarantee described in the module docstring).
    if not mapped:
        return 0, 0
    preserved = [line for line in base.results if not _inside(line.bbox, inner_box)]
    removed = len(base.results) - len(preserved)
    base.results = sorted(preserved + mapped, key=lambda line: (line.bbox[1], line.bbox[0]))
    # OcrLine has no stable identity of its own; record (text, rounded bbox)
    # tuples so _line_catalog can later recognize which lines came from a
    # repair after they have been copied (model_copy) into base.results.
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
    source: Path,
    options: ProcessingOptions,
    selected: list[int] | None,
    *,
    ocr_url: str = OCR_URL,
) -> ParsedDocument:
    """Parse one document and apply bounded hard-region repair behind one interface."""
    run_id = REGISTRY.start()
    issues: list[ProcessingIssue] = []
    receipts: list[RepairReceipt] = []
    try:
        # Cheap one-page, no-OCR probe purely to learn total_pages before
        # committing to (and billing for) the real OCR-enabled parse below.
        preflight = LiteParse(ocr_enabled=False, max_pages=1, quiet=True).parse(source)
        if selected and max(selected) > preflight.total_pages:
            raise ValueError("Page selection exceeds document page count")
        if not selected and preflight.total_pages > MAX_PAGES:
            raise ValueError("Document exceeds 100 pages; select at most 100 pages")

        base_result = _parser(options, run_id, OcrStage.BASE, ocr_url=ocr_url).parse(source)
        candidates = _page_regions(base_result, run_id, options)
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
        base_records = records_by_page(base_result, run_id, REGISTRY)
        for number, (region, digest) in enumerate(candidates, start=1):
            shot = shots[region.page]
            crop = padded_crop(region.bbox, shot.width, shot.height)
            region_id = f"p{region.page}-r{number:03d}"
            try:
                if options.experimental_peer_evidence:
                    peer = select_peer_evidence(base_result, base_records, region.page, region.bbox)
                    if peer is not None:
                        REGISTRY.set_peer(run_id, region_id, peer.image_bytes)
                repair_parser = _parser(
                    options,
                    run_id,
                    OcrStage.REPAIR,
                    ocr_url=ocr_url,
                    ocr_server_headers={
                        "X-Run-ID": run_id,
                        "X-OCR-Stage": OcrStage.REPAIR.value,
                        "X-Region-ID": region_id,
                        "X-Accuracy-Policy": options.accuracy_policy.value,
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
                if repair.verification == "disagreement":
                    raise RuntimeError("repair OCR reads disagreed")
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
                    RepairReceipt(
                        region.page,
                        region_id,
                        point_box,
                        region.reason,
                        removed,
                        added,
                        repair.verification,
                        repair.ocr_calls,
                    )
                )
            except Exception as error:
                LOGGER.exception("Hard-region repair failed for page %s", region.page)
                # Fragile by construction: this matches the literal wording of
                # the "repair OCR reads disagreed" RuntimeError raised above.
                # Changing that message without updating this check would
                # silently reclassify disagreements as generic repair_failed.
                disagreement = "disagreed" in str(error)
                issues.append(
                    ProcessingIssue(
                        "repair_disagreement" if disagreement else "repair_failed",
                        (
                            "Independent 400-DPI OCR reads disagreed; retained the 300-DPI region"
                            if disagreement
                            else "400-DPI repair failed; retained the 300-DPI region"
                        ),
                        "repair",
                        page=region.page,
                    )
                )

        final_result = base_result
        if receipts:
            try:
                final_result = _parser(options, run_id, OcrStage.FINAL, ocr_url=ocr_url).parse(
                    source
                )
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
                page.width,
                page.height,
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
        annotated_pdf = b""
        if options.generate_annotated_pdf:
            try:
                annotated_pdf = build_annotated_pdf(
                    final_result.screenshots, final_result.pages, lines
                )
            except Exception:
                LOGGER.exception("Annotated PDF generation failed")
                issues.append(
                    ProcessingIssue(
                        "annotation_failed",
                        "Annotated PDF generation failed; Markdown remains available",
                        "annotation",
                    )
                )
        return ParsedDocument(
            markdown=final_result.text,
            pages=parsed_pages,
            lines=lines,
            repairs=tuple(receipts),
            issues=tuple(issues),
            source_page_count=preflight.total_pages,
            processed_pages=tuple(page.page_num for page in final_result.pages),
            prompt_template_hashes=tuple(sorted(prompt_hashes)),
            annotated_pdf=annotated_pdf,
        )
    finally:
        # Guarantee the run-scoped OCR cache is dropped on every exit path,
        # including validation failures and repair exceptions above.
        REGISTRY.finish(run_id)
