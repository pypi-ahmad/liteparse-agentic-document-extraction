"""LiteParse agentic document extraction application."""


def main() -> None:
    """Launch the packaged Streamlit ASGI application."""
    from .server import main as run_server

    run_server()
