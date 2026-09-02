"""Single-process Streamlit UI and local LiteParse OCR endpoint."""

from pathlib import Path

import streamlit as st
from starlette.routing import Route

from liteparse_agentic_document_extraction.ocr_bridge import ocr_endpoint

ROOT = Path(__file__).resolve().parent
app = st.App(
    str(ROOT / "streamlit_app.py"),
    routes=[Route("/api/ocr", ocr_endpoint, methods=["POST"])],
)

if __name__ == "__main__":
    app.run(config={"server.address": "127.0.0.1", "server.port": 9578})
