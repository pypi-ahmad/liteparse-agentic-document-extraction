"""LiteParse agentic document extraction application."""

import sys
from pathlib import Path


def main() -> None:
    """Run the local Streamlit ASGI application."""
    from streamlit.web.cli import main as streamlit_main

    launcher = Path(__file__).resolve().parents[2] / "asgi_app.py"
    sys.argv = ["streamlit", "run", str(launcher)]
    streamlit_main()
