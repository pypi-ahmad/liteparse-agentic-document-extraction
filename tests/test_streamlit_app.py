"""Headless smoke test for the Streamlit UI."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_initial_ui_renders_without_errors() -> None:
    app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
    app = AppTest.from_file(app_path).run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "Agentic document extraction"
    assert "Clear session" in [button.label for button in app.button]
    assert app.info[0].value.startswith("Upload one or more documents")
