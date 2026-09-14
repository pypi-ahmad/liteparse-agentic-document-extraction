"""Deep Terra extraction module: chunking, schemas, evidence, retries, and merge.

The load-bearing invariant of this module is validate_extraction: every
non-null value the model returns in "data" must be backed by an "evidence"
entry whose quote is a verbatim substring of cited, pre-existing
LineEvidence text. That is what makes extraction "grounded" rather than a
plain LLM answer. Next: pipeline.py's process_document, the only caller.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .models import (
    ExtractionResult,
    LineEvidence,
    ParsedDocument,
    ProcessingIssue,
    ProcessingOptions,
)
from .ocr_bridge import get_openai_client
from .prompts import load_prompt
from .settings import (
    MAX_CHUNK_CHARS,
    MAX_CHUNK_PAGES,
    MAX_SCHEMA_BYTES,
    MERGE_FAN_IN,
    MODEL_ID,
    REASONING_EFFORT,
)

# Fixed vocabulary baked into extraction_schema()'s strict enum; the model can
# only ever emit one of these codes, so adding a new one requires updating
# both this list and any prompt text that explains the codes to the model.
MODEL_ISSUE_CODES = ["missing", "ambiguous", "conflicting", "illegible", "unsupported"]


@dataclass(frozen=True, slots=True)
class ExtractionChunk:
    """One bounded page or oversized-page segment."""

    markdown: str
    lines: tuple[LineEvidence, ...]
    pages: tuple[int, ...]


def validate_user_schema(schema: dict[str, Any] | None) -> None:
    """Validate the supported strict Structured Outputs schema subset.

    These restrictions (no $ref, additionalProperties: false, every property
    required) are not house style; they are the OpenAI Structured Outputs
    "strict" mode requirements. An optional field must be modeled as a
    required, nullable property instead of an absent one.
    """
    if schema is None:
        return
    if len(json.dumps(schema).encode()) > MAX_SCHEMA_BYTES:
        raise ValueError("JSON Schema exceeds 100 KB")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Invalid JSON Schema: {exc.message}") from exc
    if schema.get("type") != "object":
        raise ValueError("JSON Schema root type must be object")

    # Iterative worklist walk (not recursion) so a deeply nested user schema
    # cannot blow the stack; traversal order does not matter here.
    pending: list[Any] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        if "$ref" in node:
            raise ValueError("JSON Schema $ref is not supported in v1")
        if node.get("type") == "object":
            properties = node.get("properties", {})
            if not isinstance(properties, dict):
                raise ValueError("JSON Schema properties must be an object")
            if node.get("additionalProperties") is not False:
                raise ValueError("Every schema object must set additionalProperties to false")
            if set(node.get("required", [])) != set(properties):
                raise ValueError(
                    "Every schema object must require all properties; use null for optional values"
                )
        pending.extend(node.values())


def generic_data_schema() -> dict[str, Any]:
    """Return the built-in document field schema."""
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


def extraction_schema(data_schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a user schema in the fixed evidence result contract."""
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
                        "quote": {"type": "string", "minLength": 1},
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
                        "code": {"type": "string", "enum": MODEL_ISSUE_CODES},
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


# RFC 6901 JSON Pointer escaping: '~' and '/' are the two characters that are
# structurally significant in a pointer, so they must be escaped in that
# order (escaping '/' first would corrupt an already-escaped '~1').
def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _leaf_pointers(value: Any, path: str = "/data") -> set[str]:
    if value is None:
        return set()
    if isinstance(value, dict):
        result: set[str] = set()
        for key, child in value.items():
            result.update(_leaf_pointers(child, f"{path}/{_escape_pointer(str(key))}"))
        return result
    if isinstance(value, list):
        result = set()
        for index, child in enumerate(value):
            result.update(_leaf_pointers(child, f"{path}/{index}"))
        return result
    return {path}


def _resolve_pointer(root: Any, pointer: str) -> Any:
    if not pointer.startswith("/data/"):
        raise KeyError(pointer)
    value = root
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _generic_metadata_path(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 5 and parts[2] == "fields" and parts[4] in {"name", "value_type"}


def validate_extraction(
    result: dict[str, Any],
    data_schema: dict[str, Any],
    catalog: Iterable[LineEvidence],
    *,
    generic_schema: bool = False,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate the complete result and return errors plus trusted evidence only.

    "Trusted" evidence is the subset that passes every check below: it cites
    known line IDs, its quote is actually contained in the text of those
    lines, and it points at a real non-null leaf in "data". Untrusted
    evidence is dropped, not kept with a warning - see extract_document,
    which only ever stores this function's second return value.
    """
    errors = [
        error.message
        for error in Draft202012Validator(extraction_schema(data_schema)).iter_errors(result)
    ]
    data = result.get("data")
    required_paths = _leaf_pointers(data)
    if generic_schema:
        # document_type/fields[].name/value_type are schema metadata the model
        # chose to shape its own answer, not extracted facts, so they are
        # exempt from needing a citation (see _generic_metadata_path).
        required_paths = {path for path in required_paths if not _generic_metadata_path(path)}

    known = {line.id: line for line in catalog}
    covered: set[str] = set()
    trusted: list[dict[str, Any]] = []
    for index, evidence in enumerate(result.get("evidence", [])):
        prefix = f"evidence[{index}]"
        path = str(evidence.get("path", ""))
        try:
            _resolve_pointer(result, path)
        # PEP 758 (Python 3.14+): comma-separated exception types without
        # parentheses, equivalent to except (KeyError, IndexError, ...).
        except KeyError, IndexError, TypeError, ValueError:
            errors.append(f"{prefix} has unknown data pointer {path!r}")
            continue
        ids = evidence.get("line_ids", [])
        if not ids or any(line_id not in known for line_id in ids):
            errors.append(f"{prefix} contains unknown or empty line IDs")
            continue
        quote = " ".join(str(evidence.get("quote", "")).split())
        cited = " ".join(" ".join(known[line_id].text.split()) for line_id in ids)
        if not quote or quote.casefold() not in cited.casefold():
            errors.append(f"{prefix} quote is empty or absent from cited lines")
            continue
        if path not in required_paths:
            errors.append(f"{prefix} does not point to a non-null data leaf")
            continue
        covered.add(path)
        trusted.append(evidence)

    for path in sorted(required_paths - covered):
        errors.append(f"non-null value {path!r} has no valid evidence")

    status = result.get("status")
    issues = result.get("issues", [])
    if status == "complete" and (data is None or issues):
        errors.append("complete status requires non-null data and no issues")
    if status == "partial" and (data is None or not issues):
        errors.append("partial status requires usable data and at least one issue")
    if status == "failed" and (data is not None or not issues):
        errors.append("failed status requires null data and at least one issue")
    return errors, trusted


def _catalog_text(lines: Iterable[LineEvidence]) -> str:
    return "\n".join(
        f"{line.id} | p{line.page} | {list(round(v, 2) for v in line.bbox)} | {line.text}"
        for line in lines
    )


def _chunks(parsed: ParsedDocument) -> list[ExtractionChunk]:
    """Bin-pack pages into chunks under MAX_CHUNK_PAGES/MAX_CHUNK_CHARS.

    Oversized pages are split further; a page split with no line evidence at
    all (see the `not lines` branch below) produces chunks with an empty
    catalog, which validate_extraction can never satisfy - any value
    extracted from such a chunk is upgraded to an issue, not silently kept.
    """
    by_id = {line.id: line for line in parsed.lines}
    chunks: list[ExtractionChunk] = []
    page_group: list[Any] = []
    size = 0

    def flush() -> None:
        nonlocal page_group, size
        if not page_group:
            return
        ids = tuple(line_id for page in page_group for line_id in page.line_ids)
        lines = tuple(by_id[line_id] for line_id in ids if line_id in by_id)
        chunks.append(
            ExtractionChunk(
                markdown="\n\n".join(page.markdown for page in page_group),
                lines=lines,
                pages=tuple(page.page for page in page_group),
            )
        )
        page_group, size = [], 0

    for page in parsed.pages:
        lines = tuple(by_id[line_id] for line_id in page.line_ids if line_id in by_id)
        page_size = len(page.markdown) + len(_catalog_text(lines))
        if page_size > MAX_CHUNK_CHARS:
            flush()
            if not lines:
                for offset in range(0, len(page.markdown), MAX_CHUNK_CHARS):
                    chunks.append(
                        ExtractionChunk(
                            markdown=page.markdown[offset : offset + MAX_CHUNK_CHARS],
                            lines=(),
                            pages=(page.page,),
                        )
                    )
                continue
            line_group: list[LineEvidence] = []
            line_size = 0
            for line in lines:
                rendered = _catalog_text((line,))
                if line_group and line_size + len(rendered) > MAX_CHUNK_CHARS:
                    chunks.append(
                        ExtractionChunk(
                            markdown="\n".join(item.text for item in line_group),
                            lines=tuple(line_group),
                            pages=(page.page,),
                        )
                    )
                    line_group, line_size = [], 0
                line_group.append(line)
                line_size += len(rendered)
            if line_group:
                chunks.append(
                    ExtractionChunk(
                        markdown="\n".join(item.text for item in line_group),
                        lines=tuple(line_group),
                        pages=(page.page,),
                    )
                )
            continue
        if page_group and (
            len(page_group) >= MAX_CHUNK_PAGES or size + page_size > MAX_CHUNK_CHARS
        ):
            flush()
        page_group.append(page)
        size += page_size
    flush()
    return chunks


def _model_call(
    *,
    kind: str,
    payload: str,
    lines: tuple[LineEvidence, ...],
    options: ProcessingOptions,
    data_schema: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    developer_name = "extract-developer.md" if kind == "extract" else "merge-developer.md"
    user_name = "extract-user.md" if kind == "extract" else "merge-user.md"
    developer_prompt, developer_hash = load_prompt(developer_name)
    feedback = "None. This is the first attempt."
    hashes = (developer_hash,)
    last_result: dict[str, Any] = {
        "status": "failed",
        "data": None,
        "evidence": [],
        "issues": [
            {
                "path": None,
                "code": "unsupported",
                "message": "No output",
                "page": None,
                "bbox": None,
            }
        ],
    }
    for _ in range(2):
        values = {
            "INSTRUCTIONS": options.instructions.strip(),
            "SCHEMA_DESCRIPTION": json.dumps(
                data_schema, ensure_ascii=False, separators=(",", ":")
            ),
            "LINE_CATALOG": _catalog_text(lines),
            "VALIDATION_ERRORS": feedback,
        }
        if kind == "extract":
            values["DOCUMENT"] = payload
        else:
            values["PARTIAL_RESULTS"] = payload
        user_prompt, user_hash = load_prompt(user_name, **values)
        hashes = (developer_hash, user_hash)
        response = get_openai_client().responses.create(
            model=MODEL_ID,
            reasoning={"effort": REASONING_EFFORT},
            store=False,
            input=[
                {"role": "developer", "content": developer_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "document_extraction",
                    "strict": True,
                    "schema": extraction_schema(data_schema),
                }
            },
        )
        if response.output_text:
            last_result = json.loads(response.output_text)
            errors, trusted = validate_extraction(
                last_result, data_schema, lines, generic_schema=options.schema is None
            )
        else:
            errors, trusted = ["Terra returned no extraction output"], []
        if not errors:
            last_result["evidence"] = trusted
            return last_result, hashes
        feedback = "\n".join(f"- {error}" for error in errors)
    last_result["status"] = "partial" if last_result.get("data") is not None else "failed"
    last_result["evidence"] = validate_extraction(
        last_result, data_schema, lines, generic_schema=options.schema is None
    )[1]
    last_result.setdefault("issues", []).append(
        {
            "path": None,
            "code": "unsupported",
            "message": "Local evidence validation failed after retry",
            "page": None,
            "bbox": None,
        }
    )
    return last_result, hashes


def _issues(raw: Iterable[dict[str, Any]], stage: str) -> list[ProcessingIssue]:
    return [
        ProcessingIssue(
            code=str(item.get("code", "unsupported")),
            message=str(item.get("message", "Unspecified extraction issue"))[:500],
            stage=stage,
            page=item.get("page"),
            bbox=tuple(item["bbox"]) if item.get("bbox") else None,
            path=item.get("path"),
        )
        for item in raw
    ]


def extract_document(parsed: ParsedDocument, options: ProcessingOptions) -> ExtractionResult:
    """Extract bounded chunks and hierarchically merge their validated results."""
    data_schema = options.schema or generic_data_schema()
    chunks = _chunks(parsed)
    results: list[dict[str, Any]] = []
    issues: list[ProcessingIssue] = []
    hashes: set[str] = set()
    by_id = {line.id: line for line in parsed.lines}

    for chunk in chunks:
        try:
            result, used_hashes = _model_call(
                kind="extract",
                payload=chunk.markdown,
                lines=chunk.lines,
                options=options,
                data_schema=data_schema,
            )
            hashes.update(used_hashes)
            results.append(result)
            issues.extend(_issues(result.get("issues", []), "extraction"))
        except Exception:
            issues.append(
                ProcessingIssue(
                    code="extraction_chunk_failed",
                    message="Terra extraction failed for a document chunk",
                    stage="extraction",
                    page=chunk.pages[0] if chunk.pages else None,
                )
            )

    if not results:
        return ExtractionResult("failed", None, (), tuple(issues), tuple(sorted(hashes)))

    # Tree reduction: merge groups of up to MERGE_FAN_IN partials per model
    # call, then repeat on the merged results, until one remains. Keeps any
    # single merge call's input bounded regardless of total chunk count.
    while len(results) > 1:
        merged: list[dict[str, Any]] = []
        for offset in range(0, len(results), MERGE_FAN_IN):
            group = results[offset : offset + MERGE_FAN_IN]
            if len(group) == 1:
                merged.append(group[0])
                continue
            cited_ids = {
                line_id
                for result in group
                for evidence in result.get("evidence", [])
                for line_id in evidence.get("line_ids", [])
            }
            lines = tuple(by_id[line_id] for line_id in cited_ids if line_id in by_id)
            try:
                result, used_hashes = _model_call(
                    kind="merge",
                    payload=json.dumps(group, ensure_ascii=False, separators=(",", ":")),
                    lines=lines,
                    options=options,
                    data_schema=data_schema,
                )
                hashes.update(used_hashes)
                merged.append(result)
            except Exception:
                merged.append(group[0])
                issues.append(
                    ProcessingIssue(
                        code="extraction_merge_failed",
                        message="Terra could not merge one group of partial results",
                        stage="extraction",
                    )
                )
        results = merged

    final = results[0]
    issues.extend(_issues(final.get("issues", []), "extraction"))
    # ProcessingIssue is a frozen, hashable dataclass; dict.fromkeys() dedupes
    # while preserving first-seen order (a plain set would not).
    issues = list(dict.fromkeys(issues))
    status = str(final.get("status", "failed"))
    if issues and status == "complete":
        status = "partial"
    return ExtractionResult(
        status=status,
        data=final.get("data"),
        evidence=tuple(final.get("evidence", [])),
        issues=tuple(issues),
        prompt_template_hashes=tuple(sorted(hashes)),
    )
