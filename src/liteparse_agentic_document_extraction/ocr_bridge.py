"""Local LiteParse HTTP OCR bridge backed by GPT-5.6 Terra.

LiteParse (an external library) calls back into this app's own loopback HTTP
endpoint (ocr_endpoint) to get OCR for each rendered page, rather than this
app calling LiteParse's OCR hooks directly in-process. OcrRegistry is the
per-run state that makes that indirection safe: it isolates concurrent
documents from each other and caches by image content so the same rendered
page is never billed to Terra twice. Next: repair.py, the only caller of
OcrRegistry.recognize.
"""

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

from .consensus import resolve_ocr_reads
from .models import AccuracyPolicy, HardRegion, OcrLine, OcrOutput, OcrStage
from .prompts import load_prompt
from .settings import (
    MAX_RENDERED_PIXELS,
    MODEL_ID,
    OPENAI_TIMEOUT_SECONDS,
    REASONING_EFFORT,
)

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
    prompt_hashes: tuple[str, ...]
    region_id: str | None = None
    repaired_fingerprints: set[tuple[str, float, float, float, float]] = field(default_factory=set)
    verification: str = "legacy"
    ocr_calls: int = 1


@dataclass(slots=True)
class RunCache:
    """Short-lived OCR state isolated to one document run."""

    base: dict[str, OcrPageRecord] = field(default_factory=dict)
    repairs: dict[str, OcrPageRecord] = field(default_factory=dict)
    peers: dict[str, bytes] = field(default_factory=dict)


@lru_cache(maxsize=1)
def get_openai_client() -> OpenAI:
    """Create one SDK client using process environment configuration."""
    return OpenAI(timeout=OPENAI_TIMEOUT_SECONDS, max_retries=2)


def image_digest(image_bytes: bytes) -> tuple[str, int, int]:
    """Hash decoded pixels so equivalent PNG encodings share a cache key.

    Also the single enforcement point for MAX_RENDERED_PIXELS: every caller
    that needs a cache key gets the size check for free, so there is no
    separate "validate this image" step elsewhere in the pipeline.
    """
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
        if width * height > MAX_RENDERED_PIXELS:
            raise ValueError("Rendered image exceeds the 40-million-pixel limit")
        rgb = image.convert("RGB")
        payload = width.to_bytes(4, "big") + height.to_bytes(4, "big") + rgb.tobytes()
    return sha256(payload).hexdigest(), width, height


def _bounded_output(output: OcrOutput, width: int, height: int) -> OcrOutput:
    """Discard invalid model geometry before LiteParse consumes it.

    Trust boundary: Terra's returned bboxes/polygons are untrusted model
    output and are clamped to the image bounds here before anything
    downstream (repair coordinate mapping, annotated PDF drawing, evidence
    citations) does arithmetic on them.
    """
    lines: list[OcrLine] = []
    for line in output.results:
        x1, y1, x2, y2 = line.bbox
        box = (max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2))
        if box[2] > box[0] and box[3] > box[1] and line.text.strip():
            polygon = None
            if line.polygon:
                points = [
                    [
                        min(float(width), max(0.0, point[0])),
                        min(float(height), max(0.0, point[1])),
                    ]
                    for point in line.polygon
                    if len(point) >= 2
                ]
                polygon = points if len(points) >= 3 else None
            lines.append(
                line.model_copy(
                    update={"text": line.text.strip(), "bbox": list(box), "polygon": polygon}
                )
            )

    regions: list[HardRegion] = []
    for region in output.hard_regions:
        x1, y1, x2, y2 = region.bbox
        box = (max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2))
        if box[2] > box[0] and box[3] > box[1]:
            regions.append(region.model_copy(update={"bbox": list(box)}))
    return OcrOutput(results=lines, hard_regions=regions)


def call_terra_ocr(
    image_bytes: bytes,
    language: str,
    width: int,
    height: int,
    peer_image_bytes: bytes | None = None,
) -> OcrPageRecord:
    """OCR and inspect one page image with Terra.

    peer_image_bytes, when given, is attached as a *second* input image in
    the same request (see prompts/ocr-peer-user.md) - extra visual context
    for one call, not a second independent read. That is a distinct mechanism
    from the repeated-call voting in OcrRegistry.recognize below; the two
    should not be confused.
    """
    developer_prompt, developer_hash = load_prompt("ocr-developer.md")
    user_prompt, user_hash = load_prompt(
        "ocr-user.md", LANGUAGE=language or "auto", WIDTH=str(width), HEIGHT=str(height)
    )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    user_content: list[dict[str, Any]] = [
        {"type": "input_text", "text": user_prompt},
        {
            "type": "input_image",
            "image_url": f"data:image/png;base64,{encoded}",
            "detail": "original",
        },
    ]
    prompt_hashes = [developer_hash, user_hash]
    if peer_image_bytes:
        peer_prompt, peer_hash = load_prompt("ocr-peer-user.md")
        user_content.extend(
            [
                {"type": "input_text", "text": peer_prompt},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,"
                    + base64.b64encode(peer_image_bytes).decode("ascii"),
                    "detail": "original",
                },
            ]
        )
        prompt_hashes.append(peer_hash)
    request_input: Any = [
        {
            "role": "developer",
            "content": [{"type": "input_text", "text": developer_prompt}],
        },
        {"role": "user", "content": user_content},
    ]
    response = get_openai_client().responses.parse(
        model=MODEL_ID,
        reasoning={"effort": REASONING_EFFORT},
        store=False,
        input=request_input,
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
        prompt_hashes=tuple(prompt_hashes),
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

    def set_peer(self, run_id: str, region_id: str, image_bytes: bytes) -> None:
        """Attach optional document-local visual evidence to one repair region."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise PermissionError("inactive OCR run")
            run.peers[region_id] = image_bytes

    def recognize(
        self,
        run_id: str,
        stage: OcrStage,
        region_id: str | None,
        image_bytes: bytes,
        language: str,
        accuracy_policy: AccuracyPolicy = AccuracyPolicy.ACCURACY,
    ) -> list[OcrLine]:
        """Return cached OCR or call Terra, recording base and repair results.

        BASE/FINAL results are cached by pixel digest (the same rendered page
        can be OCR'd twice, e.g. once at BASE and again at FINAL after other
        pages were repaired); REPAIR results are cached by region_id instead,
        since each repair crop is unique. The lock is released before the
        (slow, network-bound) Terra calls and re-acquired after, so one
        run's repair does not block other concurrent runs; the run-existence
        check is repeated after re-acquiring in case the run finished while
        this call was in flight.
        """
        digest, width, height = image_digest(image_bytes)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise PermissionError("inactive OCR run")
            if stage in {OcrStage.BASE, OcrStage.FINAL} and digest in run.base:
                return list(run.base[digest].results)
            if stage is OcrStage.REPAIR and region_id and region_id in run.repairs:
                return list(run.repairs[region_id].results)
            peer_image = run.peers.get(region_id, b"") if region_id else b""

        record = call_terra_ocr(image_bytes, language, width, height, peer_image or None)
        # Repeated-read voting only applies to repairs under the accuracy
        # policy: two independent Terra calls, with a third tie-breaking read
        # only if the first two disagree (see consensus.resolve_ocr_reads).
        if stage is OcrStage.REPAIR and accuracy_policy is AccuracyPolicy.ACCURACY:
            second = call_terra_ocr(image_bytes, language, width, height, peer_image or None)
            consensus = resolve_ocr_reads(record.results, second.results)
            if not consensus.accepted:
                third = call_terra_ocr(image_bytes, language, width, height, peer_image or None)
                consensus = resolve_ocr_reads(record.results, second.results, third.results)
            record.results = list(consensus.lines)
            record.verification = consensus.status
            record.ocr_calls = consensus.calls
        record.region_id = region_id
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise PermissionError("inactive OCR run")
            if stage is OcrStage.REPAIR and region_id:
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


REGISTRY = OcrRegistry()


async def ocr_endpoint(request: Request) -> Response:
    """Serve LiteParse's multipart OCR contract on loopback only.

    Security boundary: this route is mounted on the same ASGI app as the
    public Streamlit UI, so the loopback check below is what keeps it from
    being a general-purpose OCR proxy for anyone who can reach the app.
    run_id doubles as a capability token - an unguessable UUID minted by
    OcrRegistry.start - not a user identity.
    """
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
        try:
            stage = OcrStage(request.headers.get("x-ocr-stage", OcrStage.BASE))
        except ValueError:
            return JSONResponse({"error": "invalid OCR stage"}, status_code=400)
        region_id = request.headers.get("x-region-id")
        try:
            accuracy_policy = AccuracyPolicy(
                request.headers.get("x-accuracy-policy", AccuracyPolicy.ACCURACY)
            )
        except ValueError:
            return JSONResponse({"error": "invalid accuracy policy"}, status_code=400)
        lines = await run_in_threadpool(
            REGISTRY.recognize,
            run_id,
            stage,
            region_id,
            image_bytes,
            language,
            accuracy_policy,
        )
        return JSONResponse(
            {
                "results": [
                    line.model_dump(
                        include={"text", "bbox", "confidence", "polygon"},
                        exclude_none=True,
                        mode="json",
                    )
                    for line in lines
                ]
            }
        )
    except Exception:  # boundary: convert provider/parser errors to safe HTTP response
        LOGGER.exception("OCR request failed")
        return JSONResponse({"error": "OCR processing failed"}, status_code=502)
