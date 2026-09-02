"""Tests for Terra OCR response handling and local route isolation."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from liteparse_agentic_document_extraction.models import HardRegion, OcrLine, OcrOutput
from liteparse_agentic_document_extraction.ocr_bridge import (
    REGISTRY,
    OcrPageRecord,
    OcrRegistry,
    call_terra_ocr,
    image_digest,
    ocr_endpoint,
    receipt_json,
)


def png_bytes(width: int = 100, height: int = 100) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def record(image: bytes, lines: list[OcrLine], region_id: str | None = None) -> OcrPageRecord:
    digest, width, height = image_digest(image)
    return OcrPageRecord(digest, width, height, lines, [], "a" * 64, region_id)


def test_pixel_digest_ignores_png_encoding() -> None:
    first = png_bytes()
    output = io.BytesIO()
    Image.open(io.BytesIO(first)).save(output, format="PNG", compress_level=0)
    assert image_digest(first) == image_digest(output.getvalue())


def test_call_terra_ocr_bounds_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    output = OcrOutput(
        results=[OcrLine(text=" Text ", bbox=(1, 2, 120, 130), confidence=0.8)],
        hard_regions=[HardRegion(bbox=(2, 3, 200, 220), reason="blur")],
    )
    calls: list[dict[str, Any]] = []

    class Responses:
        def parse(self, **kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=output)

    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.ocr_bridge.get_openai_client",
        lambda: SimpleNamespace(responses=Responses()),
    )
    result = call_terra_ocr(png_bytes(), "en", 100, 100)
    assert result.results[0].text == "Text"
    assert result.results[0].bbox == [1, 2, 100.0, 100.0]
    assert result.hard_regions[0].bbox == [2, 3, 100.0, 100.0]
    assert calls[0]["reasoning"] == {"effort": "medium"}
    assert calls[0]["input"][0]["content"][1]["detail"] == "original"


def test_registry_cache_and_atomic_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = OcrRegistry()
    run_id = registry.start()
    base_image = png_bytes(100, 100)
    repair_image = png_bytes(80, 80)
    base_lines = [
        OcrLine(text="outside", bbox=(5, 5, 20, 15), confidence=0.9),
        OcrLine(text="wrong", bbox=(40, 40, 60, 50), confidence=0.4),
    ]
    repair_lines = [OcrLine(text="right", bbox=(20, 20, 60, 40), confidence=0.95)]
    calls = iter([record(base_image, base_lines), record(repair_image, repair_lines, "r1")])
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.ocr_bridge.call_terra_ocr",
        lambda *_args: next(calls),
    )
    assert len(registry.recognize(run_id, "base", None, base_image, "auto")) == 2
    registry.recognize(run_id, "repair", "r1", repair_image, "auto")
    digest, _, _ = image_digest(base_image)
    repair = registry.repair_record(run_id, "r1")
    assert repair is not None
    removed, added = registry.patch_base(
        run_id, digest, (30, 30, 70, 70), (0.2, 0.2, 0.2, 0.2), repair
    )
    assert (removed, added) == (1, 1)
    final = registry.recognize(run_id, "final", None, base_image, "auto")
    assert [line.text for line in final] == ["outside", "right"]
    registry.finish(run_id)
    assert not registry.exists(run_id)
    assert registry.base_record(run_id, digest) is None
    with pytest.raises(PermissionError):
        registry.recognize(run_id, "base", None, base_image, "auto")


def test_ocr_endpoint_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = REGISTRY.start()
    image = png_bytes()
    monkeypatch.setattr(
        "liteparse_agentic_document_extraction.ocr_bridge.call_terra_ocr",
        lambda *_args: record(image, [OcrLine(text="hello", bbox=(1, 2, 30, 10), confidence=0.9)]),
    )
    app = Starlette(routes=[Route("/ocr", ocr_endpoint, methods=["POST"])])
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/ocr",
            headers={"X-Run-ID": run_id, "X-OCR-Stage": "base"},
            files={"file": ("page.png", image, "image/png")},
            data={"language": "en"},
        )
        assert response.status_code == 200
        assert response.json()["results"][0]["text"] == "hello"
        assert client.post("/ocr", files={"file": ("page.png", image)}).status_code == 403
    REGISTRY.finish(run_id)


def test_ocr_endpoint_rejects_remote_and_bad_requests() -> None:
    app = Starlette(routes=[Route("/ocr", ocr_endpoint, methods=["POST"])])
    with TestClient(app, client=("203.0.113.1", 50000)) as remote:
        assert remote.post("/ocr").status_code == 403

    run_id = REGISTRY.start()
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.post("/ocr", headers={"X-Run-ID": run_id}).status_code == 413
        response = client.post(
            "/ocr",
            headers={"X-Run-ID": run_id, "Content-Length": "1"},
            data={"language": "en"},
        )
        assert response.status_code == 400
    REGISTRY.finish(run_id)


def test_receipt_metadata() -> None:
    image = png_bytes()
    value = record(image, [OcrLine(text="x", bbox=(1, 1, 2, 2), confidence=1.0)])
    assert receipt_json(value) == {
        "prompt_hash": "a" * 64,
        "width": 100,
        "height": 100,
        "line_count": 1,
    }


def test_invalid_ocr_line() -> None:
    with pytest.raises(ValueError, match="bbox"):
        OcrLine(text="bad", bbox=(10, 10, 5, 5), confidence=0.5)
