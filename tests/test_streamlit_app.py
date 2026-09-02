"""Headless smoke test for the Streamlit UI."""

from streamlit.testing.v1 import AppTest


def test_initial_ui_renders_without_errors() -> None:
    def render_ui() -> None:
        import runpy

        import liteparse_agentic_document_extraction.ui

        runpy.run_path(liteparse_agentic_document_extraction.ui.__file__)

    app = AppTest.from_function(render_ui).run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "Agentic document extraction"
    assert "Clear session" in [button.label for button in app.button]
    assert app.info[0].value.startswith("Upload one or more documents")
    assert app.segmented_control(key="page_scope").value == "All"

    app.segmented_control(key="page_scope").set_value("Range").run()
    assert [item.label for item in app.number_input] == ["Start page", "End page"]
    assert not app.exception

    app.button(key="FormSubmitter:processing_options-Process files").click().run()
    assert app.error[0].value == "Upload at least one document."

    next(button for button in app.button if button.label == "Clear session").click().run()
    assert not app.exception
