"""LiteParse agentic document extraction application.

Package entry point only; see server.py for the actual ASGI app and ui.py
for the Streamlit interface it runs.
"""


def main() -> None:
    """Launch the packaged Streamlit ASGI application."""
    from .server import main as run_server

    run_server()
