"""Packaged Streamlit UI and private LiteParse OCR route.

Mounts ocr_endpoint on the same ASGI app as the Streamlit UI so the loopback
OCR callback (see settings.OCR_URL) is served from the single process this
app already runs as. Next: ui.py, the Streamlit script this app runs.
"""

from pathlib import Path

import streamlit as st
from starlette.routing import Route

from .ocr_bridge import ocr_endpoint
from .settings import APP_HOST, APP_PORT

UI_PATH = Path(__file__).with_name("ui.py")
app = st.App(str(UI_PATH), routes=[Route("/api/ocr", ocr_endpoint, methods=["POST"])])


def main() -> None:
    """Run the local single-process application."""
    app.run(config={"server.address": APP_HOST, "server.port": APP_PORT})
