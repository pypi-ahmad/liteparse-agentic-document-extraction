"""Local LiteParse HTTP OCR bridge backed by GPT-5.6 Terra."""

from __future__ import annotations

import base64
import io
import logging
import threading
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from hashlib import sha256
from typing import Any

from openai import OpenAI
from PIL import Image
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .models import MODEL_ID, REASONING_EFFORT, HardRegion, OcrLine, OcrOutput
from .prompts import load_prompt

LOGGER = logging.getLogger(__name__)
MAX_OCR_BODY_BYTES = 30 * 1024 * 1024


@dataclass(slots=True)
class OcrPageRecord:
    """OCR response cached for one rendered image."""

    digest: str
    width: int
    height: int
    results: list[OcrLine]
    hard_regions: list[HardRegion]
    prompt_hash: str
    region_id: str | None = None


@dataclass(slots=True)
class RunCache:
    """Short-lived OCR state isolated to one document run."""

    base: dict[str, OcrPageRecord] = field(default_factory=dict)
    repairs: dict[str, OcrPageRecord] = field(default_factory=dict)


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Create one SDK client using process environment configuration."""
    return OpenAI()


def image_digest(image_bytes: bytes) -> tuple[str, int, int]:
    """Hash decoded pixels so equivalent PNG encodings share a cache key."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        payload = width.to_bytes(4, "big") + height.to_bytes(4, "big") + rgb.tobytes()
    return sha256(payload).hexdigest(), width, height


def _bounded_output(output: OcrOutput, width: int, height: int) -> OcrOutput:
    """Discard invalid model geometry before LiteParse consumes it."""
    lines: list[OcrLine] = []
    for line in output.results:
        x1, y1, x2, y2 = line.bbox
        box = (max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2))
        if box[2] > box[0] and box[3] > box[1] and line.text.strip():
            lines.append(line.model_copy(update={"text": line.text.strip(), "bbox": list(box)}))

    regions: list[HardRegion] = []
    for region in output.hard_regions:
        x1, y1, x2, y2 = region.bbox
        box = (max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2))
        if box[2] > box[0] and box[3] > box[1]:
            regions.append(region.model_copy(update={"bbox": list(box)}))
    return OcrOutput(results=lines, hard_regions=regions)


def call_terra_ocr(image_bytes: bytes, language: str, width: int, height: int) -> OcrPageRecord:
    """OCR and inspect one page image with Terra."""
    prompt, prompt_hash = load_prompt(
        "ocr.md", LANGUAGE=language or "auto", WIDTH=str(width), HEIGHT=str(height)
    )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = get_openai_client().responses.parse(
        model=MODEL_ID,
        reasoning={"effort": REASONING_EFFORT},
        store=False,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{encoded}",
                        "detail": "original",
                    },
                ],
            }
        ],
        text_format=OcrOutput,
    )
    if response.output_parsed is None:
        raise RuntimeError("Terra returned no structured OCR output")
    output = _bounded_output(response.output_parsed, width, height)
    digest, _, _ = image_digest(image_bytes)
    return OcrPageRecord(
        digest=digest,
        width=width,
        height=height,
        results=output.results,
        hard_regions=output.hard_regions,
        prompt_hash=prompt_hash,
    )


class OcrRegistry:
    """Thread-safe, process-local OCR cache keyed by unguessable run IDs."""

    def __init__(self) -> None:
        self._runs: dict[str, RunCache] = {}
        self._lock = threading.RLock()

    def start(self) -> str:
        """Open an isolated document run."""
        run_id = uuid.uuid4().hex
        with self._lock:
            self._runs[run_id] = RunCache()
        return run_id

    def finish(self, run_id: str) -> None:
        """Delete all transient OCR data for a run."""
        with self._lock:
            self._runs.pop(run_id, None)

    def exists(self, run_id: str) -> bool:
        """Return whether a run token is active."""
        with self._lock:
            return run_id in self._runs

    def recognize(
        self, run_id: str, stage: str, region_id: str | None, image_bytes: bytes, language: str
    ) -> list[OcrLine]:
        """Return cached OCR or call Terra, recording base and repair results."""
        digest, width, height = image_digest(image_bytes)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise PermissionError("inactive OCR run")
            if stage in {"base", "final"} and digest in run.base:
                return list(run.base[digest].results)
            if stage == "repair" and region_id and region_id in run.repairs:
                return list(run.repairs[region_id].results)

        record = call_terra_ocr(image_bytes, language, width, height)
        record.region_id = region_id
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise PermissionError("inactive OCR run")
            if stage == "repair" and region_id:
                run.repairs[region_id] = record
            else:
                run.base[digest] = record
        return list(record.results)

    def base_record(self, run_id: str, digest: str) -> OcrPageRecord | None:
        """Get cached base-page OCR by pixel digest."""
        with self._lock:
            run = self._runs.get(run_id)
            return run.base.get(digest) if run else None

    def repair_record(self, run_id: str, region_id: str) -> OcrPageRecord | None:
        """Get one completed repair OCR record."""
        with self._lock:
            run = self._runs.get(run_id)
            return run.repairs.get(region_id) if run else None

    def patch_base(
        self,
        run_id: str,
        digest: str,
        inner_box: tuple[float, float, float, float],
        crop_box: tuple[float, float, float, float],
        repair: OcrPageRecord,
    ) -> tuple[int, int]:
        """Replace base lines inside a region with mapped 400-DPI lines."""
        with self._lock:
            run = self._runs[run_id]
            base = run.base[digest]
            left = crop_box[3] * base.width
            top = crop_box[0] * base.height
            kept_width = (1.0 - crop_box[1] - crop_box[3]) * base.width
            kept_height = (1.0 - crop_box[0] - crop_box[2]) * base.height
            scale_x = kept_width / repair.width
            scale_y = kept_height / repair.height

            def inside(box: list[float] | tuple[float, float, float, float]) -> bool:
                cx = (box[0] + box[2]) / 2
                cy = (box[1] + box[3]) / 2
                return inner_box[0] <= cx <= inner_box[2] and inner_box[1] <= cy <= inner_box[3]

            original_count = len(base.results)
            preserved = [line for line in base.results if not inside(line.bbox)]
            mapped: list[OcrLine] = []
            for line in repair.results:
                x1, y1, x2, y2 = line.bbox
                box = (
                    left + x1 * scale_x,
                    top + y1 * scale_y,
                    left + x2 * scale_x,
                    top + y2 * scale_y,
                )
                if inside(box):
                    mapped.append(line.model_copy(update={"bbox": list(box)}))
            mapped.sort(key=lambda line: (line.bbox[1], line.bbox[0]))
            base.results = sorted(preserved + mapped, key=lambda line: (line.bbox[1], line.bbox[0]))
            return original_count - len(preserved), len(mapped)


REGISTRY = OcrRegistry()


async def ocr_endpoint(request: Request) -> Response:
    """Serve LiteParse's multipart OCR contract on loopback only."""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1"}:
        return JSONResponse({"error": "OCR endpoint is local only"}, status_code=403)
    run_id = request.headers.get("x-run-id", "")
    if not REGISTRY.exists(run_id):
        return JSONResponse({"error": "inactive OCR run"}, status_code=403)
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        content_length = 0
    if content_length <= 0 or content_length > MAX_OCR_BODY_BYTES:
        return JSONResponse({"error": "invalid OCR request size"}, status_code=413)

    try:
        form = await request.form(max_files=1, max_fields=4, max_part_size=MAX_OCR_BODY_BYTES)
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            return JSONResponse({"error": "missing file"}, status_code=400)
        image_bytes = await upload.read()
        language = str(form.get("language", "auto"))
        stage = request.headers.get("x-ocr-stage", "base")
        region_id = request.headers.get("x-region-id")
        lines = await run_in_threadpool(
            REGISTRY.recognize, run_id, stage, region_id, image_bytes, language
        )
        return JSONResponse(
            {"results": [line.model_dump(exclude_none=True, mode="json") for line in lines]}
        )
    except Exception as exc:  # boundary: convert provider/parser errors to safe HTTP response
        LOGGER.warning("OCR request failed: %s", type(exc).__name__)
        return JSONResponse({"error": "OCR processing failed"}, status_code=502)


def receipt_json(record: OcrPageRecord) -> dict[str, Any]:
    """Return non-sensitive OCR provenance metadata."""
    return {
        "prompt_hash": record.prompt_hash,
        "width": record.width,
        "height": record.height,
        "line_count": len(record.results),
    }
