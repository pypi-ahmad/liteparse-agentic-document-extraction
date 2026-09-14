"""Headless smoke test for the Streamlit UI."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from liteparse_agentic_document_extraction.models import (
    DocumentArtifact,
    ProcessingOptions,
    RunStatus,
)
from liteparse_agentic_document_extraction.storage import HistoryStore, default_database_path


def render_ui() -> None:
    import runpy
    from pathlib import Path

    import liteparse_agentic_document_extraction

    ui_path = Path(liteparse_agentic_document_extraction.__file__).with_name("ui.py")
    runpy.run_path(str(ui_path))


def render_pdf() -> None:
    import streamlit as st

    st.pdf(b"%PDF-1.4\n%%EOF")


def render_copy_markdown() -> None:
    from liteparse_agentic_document_extraction.ui_components import (
        clipboard_button,
        copy_markdown_button,
    )

    copy_markdown_button("# Source", key="copy-test")
    clipboard_button("Copy formatted preview", "Source", rich_html="<h1>Source</h1>", key="rich")
    clipboard_button("Copy preview as plain text", "Source", key="plain")


def test_copy_markdown_component_renders() -> None:
    app = AppTest.from_function(render_copy_markdown).run(timeout=10)

    assert not app.exception


def test_pdf_viewer_dependency_is_available() -> None:
    app = AppTest.from_function(render_pdf).run(timeout=10)

    assert not app.exception


def test_initial_ui_renders_without_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = AppTest.from_function(render_ui).run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "Agentic document extraction"
    assert "Clear session" in [button.label for button in app.button]
    assert app.info[0].value.startswith("Upload documents")
    assert app.toggle(key="extract_data").value is False
    assert "Generate annotated PDF" in [item.label for item in app.toggle]
    assert not app.text_area
    assert app.segmented_control(key="page_scope").value == "All"

    app.segmented_control(key="page_scope").set_value("Range").run()
    assert [item.label for item in app.number_input] == ["Start page", "End page"]

    app.toggle(key="extract_data").set_value(True).run()
    assert [item.label for item in app.text_area] == ["Extraction instructions"]
    assert app.segmented_control(key="schema_mode").value == "None"
    assert not app.exception

    app.button(key="FormSubmitter:processing_options-Process files").click().run()
    assert app.error[0].value == "Upload at least one document."

    next(button for button in app.button if button.label == "Clear session").click().run()
    assert not app.exception


def test_saved_history_load_clear_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    stored = DocumentArtifact(
        "saved.pdf",
        b"source is deliberately not persisted",
        "a" * 64,
        artifact_id="saved-artifact",
        status=RunStatus.COMPLETE,
        markdown="# Saved",
        output={"schema_version": "2.1", "status": "complete"},
    )
    store = HistoryStore(default_database_path())
    store.save(stored, ProcessingOptions())

    app = AppTest.from_function(render_ui).run(timeout=10)
    assert app.selectbox(key="saved_history_id").value == "saved-artifact"

    app.button(key="load-saved-result").click().run()
    assert not app.exception
    assert app.selectbox(key="selected_artifact_id").value == "saved-artifact"
    assert [tab.label for tab in app.tabs[:5]] == [
        "Source",
        "Annotated PDF",
        "Markdown",
        "JSON",
        "Run details",
    ]
    assert any("original source file was not saved" in item.value for item in app.info)

    next(button for button in app.button if button.label == "Clear session").click().run()
    assert not app.exception
    assert store.load("saved-artifact") is not None

    app.button(key="load-saved-result").click().run()
    app.button(key="delete-saved-result").click().run()
    assert not app.exception
    assert store.load("saved-artifact") is None
