"""Bounded document parsing, repair, extraction, and export pipeline."""

from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from liteparse import LiteParse
from PIL import Image

from .models import (
    BASE_DPI,
    MODEL_ID,
    REASONING_EFFORT,
    REPAIR_DPI,
    DocumentArtifact,
    LineEvidence,
    ProcessingOptions,
    RepairReceipt,
    RunStatus,
)
from .ocr_bridge import REGISTRY, get_openai_client, image_digest
from .prompts import load_prompt

OCR_URL = "http://127.0.0.1:8501/api/ocr"
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES = 20
MAX_PAGES = 100
MAX_SCHEMA_BYTES = 100 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
ISSUE_CODES = {"missing", "ambiguous", "conflicting", "illegible", "unsupported"}


@dataclass(frozen=True, slots=True)
class Region:
    """Hard region in base screenshot pixels."""

    page: int
    bbox: tuple[float, float, float, float]
    reason: str


def safe_stem(filename: str) -> str:
    """Create a portable, non-empty archive/path stem."""
    stem = Path(filename).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned[:80] or "document"


def validate_upload(filename: str, data: bytes) -> str:
    """Validate extension, size, and basic file signature."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix or 'none'}")
    if not data:
        raise ValueError("Uploaded file is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Uploaded file exceeds 50 MB")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("File extension is PDF but content is not a PDF")
    else:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("Uploaded image is invalid") from exc
    return suffix


def parse_target_pages(value: str | None) -> list[int] | None:
    """Parse LiteParse page syntax while enforcing the 100-page work cap."""
    if value is None or not value.strip():
        return None
    pages: set[int] = set()
    for part in value.replace(" ", "").split(","):
        if not part:
            raise ValueError("Page range contains an empty item")
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError("Page range must use numbers such as 1-5,8")
            start, end = int(start_text), int(end_text)
            if start < 1 or end < start:
                raise ValueError("Page range is invalid")
            if end - start + 1 > MAX_PAGES:
                raise ValueError("Page selection exceeds 100 pages")
            pages.update(range(start, end + 1))
        elif part.isdigit() and int(part) >= 1:
            pages.add(int(part))
        else:
            raise ValueError("Page range must use numbers such as 1-5,8")
        if len(pages) > MAX_PAGES:
            raise ValueError("Page selection exceeds 100 pages")
    return sorted(pages)


def validate_user_schema(schema: dict[str, Any] | None) -> None:
    """Validate the supported strict Structured Outputs schema subset."""
    if schema is None:
        return
    if len(json.dumps(schema).encode()) > MAX_SCHEMA_BYTES:
        raise ValueError("JSON Schema exceeds 100 KB")
    Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object":
        raise ValueError("JSON Schema root type must be object")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                raise ValueError("JSON Schema $ref is not supported in v1")
            if node.get("type") == "object":
                properties = node.get("properties", {})
                if node.get("additionalProperties") is not False:
                    raise ValueError("Every schema object must set additionalProperties to false")
                if set(node.get("required", [])) != set(properties):
                    raise ValueError(
                        "Every schema object must require all properties; "
                        "use null for optional values"
                    )
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)


def _generic_data_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "document_type": {"type": ["string", "null"]},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": ["string", "null"]},
                        "value_type": {
                            "type": "string",
                            "enum": ["text", "number", "date", "boolean", "identifier", "other"],
                        },
                    },
                    "required": ["name", "value", "value_type"],
                },
            },
        },
        "required": ["document_type", "fields"],
    }


def _extraction_schema(data_schema: dict[str, Any]) -> dict[str, Any]:
    box_or_null = {
        "anyOf": [
            {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            {"type": "null"},
        ]
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": ["complete", "partial", "failed"]},
            "data": {"anyOf": [data_schema, {"type": "null"}]},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string"},
                        "line_ids": {"type": "array", "items": {"type": "string"}},
                        "quote": {"type": "string"},
                    },
                    "required": ["path", "line_ids", "quote"],
                },
            },
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": ["string", "null"]},
                        "code": {"type": "string", "enum": sorted(ISSUE_CODES)},
                        "message": {"type": "string"},
                        "page": {"type": ["integer", "null"]},
                        "bbox": box_or_null,
                    },
                    "required": ["path", "code", "message", "page", "bbox"],
                },
            },
        },
        "required": ["status", "data", "evidence", "issues"],
    }


def _boxes_touch(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    gap: float,
) -> bool:
    return not (
        first[2] + gap < second[0]
        or second[2] + gap < first[0]
        or first[3] + gap < second[1]
        or second[3] + gap < first[1]
    )


def merge_regions(regions: Iterable[Region], width: int, height: int) -> list[Region]:
    """Merge nearby hard regions and cap each page at eight repair calls."""
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
                    page=current.page,
                    bbox=(min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])),
                    reason=f"{other.reason}; {current.reason}"[:200],
                )
                merged.pop(index)
                index = 0
            else:
                index += 1
        merged.append(current)
    if len(merged) > 8:
        kept, rest = merged[:7], merged[7:]
        xs1, ys1, xs2, ys2 = zip(*(region.bbox for region in rest), strict=True)
        kept.append(
            Region(rest[0].page, (min(xs1), min(ys1), max(xs2), max(ys2)), "combined hard regions")
        )
        return kept
    return merged


def padded_crop(
    bbox: tuple[float, float, float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    """Convert a pixel bbox to LiteParse fractional crop values with 2% padding."""
    x1, y1, x2, y2 = bbox
    pad_x, pad_y = width * 0.02, height * 0.02
    left = max(0.0, x1 - pad_x) / width
    top = max(0.0, y1 - pad_y) / height
    right = 1.0 - min(float(width), x2 + pad_x) / width
    bottom = 1.0 - min(float(height), y2 + pad_y) / height
    return top, right, bottom, left


def _parser(options: ProcessingOptions, run_id: str, stage: str, **overrides: Any) -> LiteParse:
    settings: dict[str, Any] = {
        "ocr_enabled": True,
        "ocr_server_url": OCR_URL,
        "ocr_server_headers": {"X-Run-ID": run_id, "X-OCR-Stage": stage},
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


def _hard_regions(result: Any, run_id: str) -> list[tuple[Region, str]]:
    candidates: list[tuple[Region, str]] = []
    pages = {page.page_num: page for page in result.pages}
    for screenshot in result.screenshots:
        digest, width, height = image_digest(screenshot.image_bytes)
        record = REGISTRY.base_record(run_id, digest)
        if record is None:
            continue
        page = pages[screenshot.page_num]
        page_regions = [
            Region(
                page.page_num,
                (region.bbox[0], region.bbox[1], region.bbox[2], region.bbox[3]),
                region.reason,
            )
            for region in record.hard_regions
        ]
        for block in page.blocks or []:
            if block.kind == "grid_fallback" and block.bbox is not None:
                box = block.bbox
                page_regions.append(
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
        candidates.extend((region, digest) for region in merge_regions(page_regions, width, height))
    return candidates


def _line_catalog(
    result: Any, repair_boxes: dict[int, list[tuple[float, float, float, float]]]
) -> list[LineEvidence]:
    catalog: list[LineEvidence] = []
    for page in result.pages:
        for index, item in enumerate(page.text_items, start=1):
            bbox = (item.x, item.y, item.width, item.height)
            source = "native" if item.confidence is None else "ocr_300"
            center = (item.x + item.width / 2, item.y + item.height / 2)
            if any(
                box[0] <= center[0] <= box[2] and box[1] <= center[1] <= box[3]
                for box in repair_boxes.get(page.page_num, [])
            ):
                source = "repair_400"
            catalog.append(
                LineEvidence(
                    id=f"p{page.page_num}-l{index:04d}",
                    page=page.page_num,
                    text=item.text,
                    bbox=bbox,
                    source=source,
                )
            )
    return catalog


def _catalog_prompt(catalog: list[LineEvidence]) -> str:
    return "\n".join(
        f"{line.id} | p{line.page} | {list(round(value, 2) for value in line.bbox)} | {line.text}"
        for line in catalog
    )


def _resolve_pointer(root: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    value = root
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _validate_extraction(
    result: dict[str, Any], data_schema: dict[str, Any], catalog: list[LineEvidence]
) -> list[str]:
    errors: list[str] = []
    if result.get("data") is not None:
        errors.extend(
            error.message for error in Draft202012Validator(data_schema).iter_errors(result["data"])
        )
    known = {line.id: line for line in catalog}
    valid_evidence = 0
    for index, evidence in enumerate(result.get("evidence", [])):
        prefix = f"evidence[{index}]"
        path = evidence.get("path", "")
        try:
            _resolve_pointer(result, path)
        except KeyError, IndexError, TypeError, ValueError:
            errors.append(f"{prefix} has unknown JSON Pointer {path!r}")
        ids = evidence.get("line_ids", [])
        if not ids or any(line_id not in known for line_id in ids):
            errors.append(f"{prefix} contains unknown or empty line IDs")
            continue
        cited = " ".join(known[line_id].text for line_id in ids)
        quote = " ".join(str(evidence.get("quote", "")).split())
        if quote and quote.casefold() not in " ".join(cited.split()).casefold():
            errors.append(f"{prefix} quote is not present in cited lines")
        else:
            valid_evidence += 1
    if result.get("data") is not None and valid_evidence == 0:
        errors.append("extracted data has no valid evidence")
    return errors


def extract_data(
    markdown: str,
    catalog: list[LineEvidence],
    options: ProcessingOptions,
) -> tuple[dict[str, Any], str]:
    """Extract schema-shaped data and retry once when evidence is invalid."""
    data_schema = options.schema or _generic_data_schema()
    schema_description = json.dumps(data_schema, ensure_ascii=False, separators=(",", ":"))
    validation_errors = "None. This is the first attempt."
    prompt_hash = ""
    result: dict[str, Any] = {}
    errors: list[str] = []

    for _attempt in range(2):
        prompt, prompt_hash = load_prompt(
            "extract.md",
            INSTRUCTIONS=options.instructions.strip() or "Extract all salient document fields.",
            SCHEMA_DESCRIPTION=schema_description,
            DOCUMENT=markdown,
            LINE_CATALOG=_catalog_prompt(catalog),
            VALIDATION_ERRORS=validation_errors,
        )
        response = get_openai_client().responses.create(
            model=MODEL_ID,
            reasoning={"effort": REASONING_EFFORT},
            store=False,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "document_extraction",
                    "strict": True,
                    "schema": _extraction_schema(data_schema),
                }
            },
        )
        if not response.output_text:
            result = {"status": "failed", "data": None, "evidence": [], "issues": []}
            errors = ["Terra returned no extraction output"]
        else:
            result = json.loads(response.output_text)
            errors = _validate_extraction(result, data_schema, catalog)
        if not errors:
            break
        validation_errors = "\n".join(f"- {error}" for error in errors)

    if errors:
        result["status"] = "partial" if result.get("data") is not None else "failed"
        result.setdefault("issues", []).extend(
            {
                "path": None,
                "code": "invalid_evidence",
                "message": error,
                "page": None,
                "bbox": None,
            }
            for error in errors
        )
    return result, prompt_hash


def process_document(filename: str, data: bytes, options: ProcessingOptions) -> DocumentArtifact:
    """Run one document through parse, bounded repair, and extraction."""
    artifact = DocumentArtifact(filename, data, sha256(data).hexdigest(), status=RunStatus.PARSING)
    try:
        suffix = validate_upload(filename, data)
        parse_target_pages(options.target_pages)
        validate_user_schema(options.schema)
    except Exception as exc:
        artifact.status = RunStatus.FAILED
        artifact.error = str(exc) if isinstance(exc, ValueError) else "Input validation failed"
        return artifact

    run_id = REGISTRY.start()
    repairs: list[RepairReceipt] = []
    repair_boxes: dict[int, list[tuple[float, float, float, float]]] = {}

    try:
        with tempfile.TemporaryDirectory(prefix="liteparse-ade-") as temp_dir:
            source = Path(temp_dir) / f"{safe_stem(filename)}{suffix}"
            source.write_bytes(data)
            preflight = LiteParse(ocr_enabled=False, max_pages=1, quiet=True).parse(source)
            selected = parse_target_pages(options.target_pages)
            if selected and max(selected) > preflight.total_pages:
                raise ValueError("Page selection exceeds document page count")
            if not selected and preflight.total_pages > MAX_PAGES:
                raise ValueError("Document exceeds 100 pages; select at most 100 pages")

            base_result = _parser(options, run_id, "base").parse(source)
            artifact.screenshots = [
                (shot.page_num, shot.image_bytes) for shot in base_result.screenshots
            ]
            candidates = _hard_regions(base_result, run_id)

            if candidates:
                artifact.status = RunStatus.REPAIRING
            shots = {shot.page_num: shot for shot in base_result.screenshots}
            pages = {page.page_num: page for page in base_result.pages}
            for number, (region, base_digest) in enumerate(candidates, start=1):
                shot = shots[region.page]
                crop = padded_crop(region.bbox, shot.width, shot.height)
                region_id = f"p{region.page}-r{number:03d}"
                headers = {
                    "X-Run-ID": run_id,
                    "X-OCR-Stage": "repair",
                    "X-Region-ID": region_id,
                }
                repair_parser = _parser(
                    options,
                    run_id,
                    "repair",
                    ocr_server_headers=headers,
                    dpi=REPAIR_DPI,
                    target_pages=str(region.page),
                    crop_box=crop,
                    extract_screenshots=False,
                    include_complexity=False,
                )
                repair_parser.parse(source)
                repair = REGISTRY.repair_record(run_id, region_id)
                if repair is None:
                    continue
                removed, added = REGISTRY.patch_base(run_id, base_digest, region.bbox, crop, repair)
                page = pages[region.page]
                point_box = (
                    region.bbox[0] / shot.width * page.width,
                    region.bbox[1] / shot.height * page.height,
                    region.bbox[2] / shot.width * page.width,
                    region.bbox[3] / shot.height * page.height,
                )
                repair_boxes.setdefault(region.page, []).append(point_box)
                repairs.append(
                    RepairReceipt(region.page, region_id, point_box, region.reason, removed, added)
                )

            final_result = (
                _parser(options, run_id, "final").parse(source) if repairs else base_result
            )
            artifact.markdown = final_result.text
            catalog = _line_catalog(final_result, repair_boxes)
            artifact.status = RunStatus.EXTRACTING
            extracted, extraction_prompt_hash = extract_data(artifact.markdown, catalog, options)
            _, ocr_prompt_hash = load_prompt("ocr.md", LANGUAGE="auto", WIDTH="0", HEIGHT="0")
            page_errors = [
                {
                    "path": None,
                    "code": "page_error",
                    "message": str(error),
                    "page": getattr(error, "page_num", None),
                    "bbox": None,
                }
                for error in final_result.page_errors
            ]
            extracted.setdefault("issues", []).extend(page_errors)
            status = extracted.get("status", "failed")
            if page_errors and status == "complete":
                status = "partial"
            artifact.status = RunStatus(status)
            catalog_by_id = {line.id: line for line in catalog}
            artifact.output = {
                "schema_version": "1.0",
                "status": status,
                "document": {
                    "id": artifact.source_hash,
                    "source_name": filename,
                    "page_count": len(final_result.pages),
                    "model": MODEL_ID,
                    "reasoning_effort": REASONING_EFFORT,
                    "base_dpi": BASE_DPI,
                    "repair_dpi": REPAIR_DPI,
                    "prompt_hashes": {
                        "ocr.md": ocr_prompt_hash,
                        "extract.md": extraction_prompt_hash,
                    },
                },
                "data": extracted.get("data"),
                "evidence": [
                    {
                        **evidence,
                        "sources": [
                            asdict(catalog_by_id[line_id])
                            for line_id in evidence["line_ids"]
                            if line_id in catalog_by_id
                        ],
                    }
                    for evidence in extracted.get("evidence", [])
                ],
                "repairs": [asdict(repair) for repair in repairs],
                "issues": extracted.get("issues", []),
            }
    except Exception as exc:
        artifact.status = RunStatus.FAILED
        artifact.error = (
            str(exc) if isinstance(exc, ValueError) else f"Processing failed ({type(exc).__name__})"
        )
    finally:
        REGISTRY.finish(run_id)
    return artifact


def artifact_json(artifact: DocumentArtifact) -> str:
    """Serialize a document result for display and download."""
    return json.dumps(artifact.output, ensure_ascii=False, indent=2)


def result_zip(artifacts: Iterable[DocumentArtifact]) -> bytes:
    """Build one in-memory ZIP containing completed Markdown and JSON outputs."""
    output = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            if artifact.status not in {RunStatus.COMPLETE, RunStatus.PARTIAL}:
                continue
            stem = safe_stem(artifact.source_name)
            if stem in used:
                stem = f"{stem}-{artifact.source_hash[:8]}"
            used.add(stem)
            archive.writestr(f"{stem}.md", artifact.markdown)
            archive.writestr(f"{stem}.json", artifact_json(artifact))
    return output.getvalue()
