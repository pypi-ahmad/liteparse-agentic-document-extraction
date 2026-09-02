"""Small public coordinator for validation, parsing, extraction, and export."""

from __future__ import annotations

import io
import json
import logging
import re
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any

from PIL import Image

from .extraction import (
    extract_document,
    validate_extraction,
    validate_user_schema,
)
from .models import DocumentArtifact, ProcessingIssue, ProcessingOptions, RunStatus
from .repair import parse_document
from .settings import (
    BASE_DPI,
    MAX_FILE_BYTES,
    MAX_PAGES,
    MODEL_ID,
    REASONING_EFFORT,
    REPAIR_DPI,
)

LOGGER = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def safe_stem(filename: str) -> str:
    """Create a portable, non-empty, Windows-safe output stem."""
    stem = Path(filename).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "document"
    return f"_{cleaned}" if cleaned.upper() in WINDOWS_RESERVED_NAMES else cleaned


def validate_upload(filename: str, data: bytes) -> str:
    """Validate extension, size, signature, and decoded image dimensions."""
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


def _issue_dict(issue: ProcessingIssue) -> dict[str, Any]:
    value = asdict(issue)
    if value["bbox"] is not None:
        value["bbox"] = list(value["bbox"])
        value["coordinate_space"] = "viewport_points_top_left_72dpi"
    return value


def _overall_status(
    markdown: str, extraction_status: str, issues: list[ProcessingIssue]
) -> RunStatus:
    if not markdown.strip():
        return RunStatus.FAILED
    if extraction_status != "complete" or issues:
        return RunStatus.PARTIAL
    return RunStatus.COMPLETE


def process_document(filename: str, data: bytes, options: ProcessingOptions) -> DocumentArtifact:
    """Run one upload while preserving usable Markdown across later-stage failures."""
    artifact = DocumentArtifact(filename, data, sha256(data).hexdigest())
    try:
        suffix = validate_upload(filename, data)
        selected = parse_target_pages(options.target_pages)
        validate_user_schema(options.schema)
    except ValueError as exc:
        artifact.error = str(exc)
        return artifact

    try:
        with tempfile.TemporaryDirectory(prefix="liteparse-ade-") as temp_dir:
            source = Path(temp_dir) / f"{safe_stem(filename)}{suffix}"
            source.write_bytes(data)
            parsed = parse_document(source, options, selected)
            artifact.markdown = parsed.markdown
            extraction_issues: list[ProcessingIssue] = []
            try:
                extracted = extract_document(parsed, options)
            except Exception:
                LOGGER.exception("Document extraction failed")
                extracted = None
                extraction_issues.append(
                    ProcessingIssue(
                        "extraction_failed",
                        "Terra extraction failed; Markdown remains available",
                        "extraction",
                    )
                )

            issues = [*parsed.issues, *extraction_issues]
            extraction_status = "failed"
            data_output = None
            evidence_output: list[dict[str, Any]] = []
            extraction_hashes: tuple[str, ...] = ()
            if extracted is not None:
                extraction_status = extracted.status
                data_output = extracted.data
                issues.extend(extracted.issues)
                extraction_hashes = extracted.prompt_template_hashes
                catalog = {line.id: line for line in parsed.lines}
                evidence_output = [
                    {
                        **evidence,
                        "sources": [
                            {
                                **asdict(catalog[line_id]),
                                "bbox": list(catalog[line_id].bbox),
                                "coordinate_space": "viewport_points_top_left_72dpi",
                            }
                            for line_id in evidence["line_ids"]
                            if line_id in catalog
                        ],
                    }
                    for evidence in extracted.evidence
                ]

            artifact.status = _overall_status(artifact.markdown, extraction_status, issues)
            artifact.output = {
                "schema_version": "2.0",
                "status": artifact.status.value,
                "stages": {
                    "parsing": "complete" if artifact.markdown else "failed",
                    "repair": "partial"
                    if any(issue.stage == "repair" for issue in issues)
                    else "complete",
                    "extraction": extraction_status,
                },
                "document": {
                    "id": artifact.source_hash,
                    "artifact_id": artifact.artifact_id,
                    "source_name": filename,
                    "source_page_count": parsed.source_page_count,
                    "processed_pages": list(parsed.processed_pages),
                    "model": MODEL_ID,
                    "reasoning_effort": REASONING_EFFORT,
                    "liteparse_version": version("liteparse"),
                    "base_dpi": BASE_DPI,
                    "repair_dpi": REPAIR_DPI,
                    "prompt_template_hashes": {
                        "ocr": list(parsed.prompt_template_hashes),
                        "extraction": list(extraction_hashes),
                    },
                },
                "data": data_output,
                "evidence": evidence_output,
                "repairs": [
                    {
                        **asdict(repair),
                        "bbox": list(repair.bbox),
                        "coordinate_space": "viewport_points_top_left_72dpi",
                    }
                    for repair in parsed.repairs
                ],
                "issues": [_issue_dict(issue) for issue in issues],
            }
            if artifact.status is RunStatus.FAILED:
                artifact.error = "Document parsing produced no usable Markdown"
    except Exception as exc:
        LOGGER.exception("Document parsing failed")
        artifact.error = str(exc) if isinstance(exc, ValueError) else "Document parsing failed"
    return artifact


def artifact_json(artifact: DocumentArtifact) -> str:
    """Serialize a document result for display and download."""
    return json.dumps(artifact.output, ensure_ascii=False, indent=2)


def result_zip(artifacts: Iterable[DocumentArtifact]) -> bytes:
    """Build one in-memory ZIP with collision-free Markdown and JSON names."""
    output = io.BytesIO()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            if not artifact.markdown:
                continue
            base = safe_stem(artifact.source_name)
            counts[base] = counts.get(base, 0) + 1
            stem = base if counts[base] == 1 else f"{base}-{counts[base]}"
            archive.writestr(f"{stem}.md", artifact.markdown)
            archive.writestr(f"{stem}.json", artifact_json(artifact))
    return output.getvalue()


def _validate_extraction(
    result: dict[str, Any], data_schema: dict[str, Any], catalog: list[Any]
) -> list[str]:
    """Compatibility wrapper for the local extraction validator."""
    return validate_extraction(result, data_schema, catalog)[0]
