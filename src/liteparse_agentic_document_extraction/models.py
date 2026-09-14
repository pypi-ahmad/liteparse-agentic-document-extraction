"""Typed application records and model response schemas.

Pydantic models (OcrLine, HardRegion, OcrOutput) validate untrusted model
output at the Terra API boundary; the frozen dataclasses below them are
internal, already-trusted pipeline state. Next: ocr_bridge.py, which produces
the pydantic models, and repair.py, which produces the dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .settings import BASE_DPI, MODEL_ID, REASONING_EFFORT, REPAIR_DPI

# (x1, y1, x2, y2), origin top-left. The unit varies by producer: OCR-stage
# boxes are pixels in the rendered screenshot, LineEvidence/RepairReceipt
# boxes are page-viewport points (72 DPI, see pipeline.py's
# "viewport_points_top_left_72dpi" tag on serialized output). Callers must
# not mix the two without an explicit DPI/scale conversion.
BBox = tuple[float, float, float, float]


def _validate_box(value: list[float]) -> list[float]:
    """Reject degenerate or negative geometry; only used by the pydantic models below.

    Plain BBox tuples on dataclasses (LineEvidence, RepairReceipt, ...) are not
    run through this check and are trusted to already be well-formed.
    """
    x1, y1, x2, y2 = value
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise ValueError("bbox must be an ordered positive rectangle")
    return value


class RunStatus(StrEnum):
    """Externally observable document result state."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class OcrStage(StrEnum):
    """Accepted stages in the private LiteParse OCR callback contract."""

    BASE = "base"
    REPAIR = "repair"
    FINAL = "final"


class AccuracyPolicy(StrEnum):
    """Available OCR repair verification policies."""

    LEGACY = "legacy"
    ACCURACY = "accuracy"


class OcrLine(BaseModel):
    """One line returned through LiteParse's HTTP OCR contract."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0.0, le=1.0)
    polygon: list[list[float]] | None = None
    source_kind: Literal["printed", "handwritten", "uncertain"] = "uncertain"
    _ordered_bbox = field_validator("bbox")(_validate_box)


class HardRegion(BaseModel):
    """Image region needing a true 400-DPI rerender."""

    model_config = ConfigDict(extra="forbid")
    bbox: list[float] = Field(min_length=4, max_length=4)
    reason: str = Field(min_length=1, max_length=200)
    _ordered_bbox = field_validator("bbox")(_validate_box)


class OcrOutput(BaseModel):
    """Structured Terra OCR response."""

    model_config = ConfigDict(extra="forbid")
    results: list[OcrLine]
    hard_regions: list[HardRegion] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProcessingOptions:
    """User-selected processing options."""

    instructions: str = ""
    schema: dict[str, Any] | None = None
    language: str = "auto"
    target_pages: str | None = None
    keep_headers_footers: bool = False
    image_mode: str = "placeholder"
    extract_data: bool = False
    generate_annotated_pdf: bool = False
    accuracy_policy: AccuracyPolicy = AccuracyPolicy.ACCURACY
    experimental_peer_evidence: bool = False


@dataclass(frozen=True, slots=True)
class ProcessingIssue:
    """One bounded, user-safe processing problem."""

    code: str
    message: str
    stage: str
    page: int | None = None
    bbox: BBox | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class LineEvidence:
    """Trusted line in top-left 72-DPI viewport coordinates."""

    id: str
    page: int
    text: str
    bbox: BBox
    source: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class RepairReceipt:
    """One applied 400-DPI repair event."""

    page: int
    region_id: str
    bbox: BBox
    reason: str
    replaced_lines: int
    added_lines: int
    # Mirrors consensus.OcrConsensus.status ("consensus"/"majority"); stays at
    # the "legacy" default when AccuracyPolicy.LEGACY skips repeated reads.
    verification: str = "legacy"
    ocr_calls: int = 1


@dataclass(frozen=True, slots=True)
class ParsedPage:
    """One page prepared for bounded extraction."""

    page: int
    markdown: str
    line_ids: tuple[str, ...]
    width: float = 0.0
    height: float = 0.0


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Result of LiteParse plus transactional hard-region repair."""

    markdown: str
    pages: tuple[ParsedPage, ...]
    lines: tuple[LineEvidence, ...]
    repairs: tuple[RepairReceipt, ...]
    issues: tuple[ProcessingIssue, ...]
    source_page_count: int
    processed_pages: tuple[int, ...]
    prompt_template_hashes: tuple[str, ...]
    annotated_pdf: bytes = b""


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Locally validated Terra extraction result."""

    status: str
    data: dict[str, Any] | None
    evidence: tuple[dict[str, Any], ...]
    issues: tuple[ProcessingIssue, ...]
    prompt_template_hashes: tuple[str, ...]


@dataclass(slots=True)
class DocumentArtifact:
    """In-memory result for one uploaded document instance.

    source_bytes lives only for the lifetime of the Streamlit session; it is
    never written to storage.py's history database (see the privacy notes in
    the project README).
    """

    source_name: str
    source_bytes: bytes
    source_hash: str
    artifact_id: str = field(default_factory=lambda: uuid4().hex)
    status: RunStatus = RunStatus.FAILED
    markdown: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    annotated_pdf: bytes = b""


__all__ = [
    "BASE_DPI",
    "MODEL_ID",
    "REASONING_EFFORT",
    "REPAIR_DPI",
    "AccuracyPolicy",
    "BBox",
    "DocumentArtifact",
    "ExtractionResult",
    "HardRegion",
    "LineEvidence",
    "OcrLine",
    "OcrOutput",
    "OcrStage",
    "ParsedDocument",
    "ParsedPage",
    "ProcessingIssue",
    "ProcessingOptions",
    "RepairReceipt",
    "RunStatus",
]
