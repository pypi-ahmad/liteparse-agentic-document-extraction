"""Typed application records and model response schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

BASE_DPI = 300
REPAIR_DPI = 400
MODEL_ID = "gpt-5.6-terra"
REASONING_EFFORT = "medium"


class RunStatus(StrEnum):
    """Document processing state."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    REPAIRING = "repairing"
    EXTRACTING = "extracting"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class OcrLine(BaseModel):
    """One line returned through LiteParse's HTTP OCR contract."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0.0, le=1.0)
    polygon: list[list[float]] | None = None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        """Require an ordered, non-empty rectangle."""
        x1, y1, x2, y2 = value
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must be an ordered positive rectangle")
        return value


class HardRegion(BaseModel):
    """Image region needing a true 400-DPI rerender."""

    model_config = ConfigDict(extra="forbid")

    bbox: list[float] = Field(min_length=4, max_length=4)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        """Require an ordered, non-empty rectangle."""
        x1, y1, x2, y2 = value
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must be an ordered positive rectangle")
        return value


class OcrOutput(BaseModel):
    """Structured Terra OCR response."""

    model_config = ConfigDict(extra="forbid")

    results: list[OcrLine]
    hard_regions: list[HardRegion] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProcessingOptions:
    """User-selected processing options."""

    instructions: str
    schema: dict[str, Any] | None = None
    language: str = "auto"
    target_pages: str | None = None
    keep_headers_footers: bool = False
    image_mode: str = "placeholder"


@dataclass(slots=True)
class DocumentArtifact:
    """In-memory result for one uploaded document."""

    source_name: str
    source_bytes: bytes
    source_hash: str
    status: RunStatus = RunStatus.UPLOADED
    markdown: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    screenshots: list[tuple[int, bytes]] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LineEvidence:
    """Trusted LiteParse line catalog entry."""

    id: str
    page: int
    text: str
    bbox: tuple[float, float, float, float]
    source: str


@dataclass(frozen=True, slots=True)
class RepairReceipt:
    """One bounded 400-DPI repair event."""

    page: int
    region_id: str
    bbox: tuple[float, float, float, float]
    reason: str
    replaced_lines: int
    added_lines: int
