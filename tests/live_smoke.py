"""Optional live synthetic end-to-end check; invokes GPT-5.6 Terra."""

import io
import threading
import time

import uvicorn
from PIL import Image, ImageDraw
from starlette.applications import Starlette
from starlette.routing import Route

from liteparse_agentic_document_extraction.models import ProcessingOptions
from liteparse_agentic_document_extraction.ocr_bridge import ocr_endpoint
from liteparse_agentic_document_extraction.pipeline import process_document


def main() -> None:
    """Run local OCR route and process one generated invoice image."""
    route_app = Starlette(routes=[Route("/api/ocr", ocr_endpoint, methods=["POST"])])
    server = uvicorn.Server(
        uvicorn.Config(route_app, host="127.0.0.1", port=8501, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("Local OCR route did not start")

    try:
        image = Image.new("RGB", (1200, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.text((80, 100), "Invoice INV-7", fill="black", font_size=60)
        draw.text((80, 220), "Total USD 42.00", fill="black", font_size=60)
        payload = io.BytesIO()
        image.save(payload, format="PNG", dpi=(300, 300))
        artifact = process_document(
            "synthetic-invoice.png",
            payload.getvalue(),
            ProcessingOptions("Extract invoice number and total."),
        )
        print(
            {
                "status": artifact.status.value,
                "markdown": artifact.markdown,
                "data": artifact.output.get("data"),
                "evidence_count": len(artifact.output.get("evidence", [])),
                "error": artifact.error,
            }
        )
        if artifact.error:
            raise RuntimeError(artifact.error)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
